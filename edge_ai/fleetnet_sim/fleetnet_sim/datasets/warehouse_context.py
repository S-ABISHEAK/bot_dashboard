"""Static per-warehouse geometry/graph context for the frozen ML feature
schemas (Congestion/Conflict/ETA). Computed once per ``layout_id`` from
the full layout JSON already stored in ``warehouses.raw_layout_json``
(see ``cli/main.py``'s ``Warehouse`` row) and reused across every
telemetry row for that layout -- these are properties of the warehouse,
not of a single simulation tick, so they never change during a run.

Edges are looked up by a canonical string key (``canon_edge(a, b)``)
rather than a raw ``(source, target)`` tuple: the navigation graph is
undirected, and ``edge_state_ts``'s ``(edge_source, edge_target)``
column order isn't guaranteed to match ``networkx``'s internal edge
iteration order, so every producer/consumer of an edge key here must
canonicalize the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
from fleetnet_layout.serialization.json_io import graph_from_json
from sqlalchemy.orm import Session

from fleetnet_sim.storage.models import Warehouse

# 2 * the default robot_radius_m (config/schema.py) -- used only as a
# rough edge-capacity reference for edge_occupancy_ratio, not a claim
# about any specific robot's real footprint.
ROBOT_DIAMETER_M = 0.7


def canon_edge(a: str, b: str) -> str:
    lo, hi = sorted((a, b))
    return f"{lo}|{hi}"


@dataclass
class EdgeContext:
    length_m: float | None
    width_m: float | None
    node_out_degree: int  # max(degree(u), degree(v)) -- see WarehouseContext docstring
    node_centrality: float  # max(degree_centrality(u), degree_centrality(v))
    bottleneck_risk_score: float
    shared_edge_flag: bool  # either endpoint is a junction (degree > 2)
    shared_node_flag: bool  # alias of the same junction test, kept distinct per the frozen spec's two separate fields


@dataclass
class WarehouseContext:
    """``node_out_degree``/``node_centrality`` are reported per-EDGE as
    ``max(endpoint_u, endpoint_v)`` -- the frozen spec doesn't disambiguate
    which endpoint an edge-level row should use, and this matches the
    same convention `warehouse_layout`'s own bottleneck-scoring formula
    already uses (``graph/metrics.py::compute_metrics``), which this
    module's ``bottleneck_risk_score`` is a direct, non-truncated
    (all-edges, not just top-10) re-application of."""

    layout_id: str
    edges: dict[str, EdgeContext] = field(default_factory=dict)
    edge_neighbors: dict[str, set[str]] = field(default_factory=dict)  # edges incident to either endpoint, for nearby-edge aggregation
    zone_type_by_node: dict[str, str] = field(default_factory=dict)  # nav-graph zone_entry nodes only
    zone_type_by_zone_id: dict[str, str] = field(default_factory=dict)  # raw geometry.zones[].id -> zone_type, e.g. "zone_in_picking" -> "picking"

    def edge(self, a: str, b: str) -> EdgeContext | None:
        return self.edges.get(canon_edge(a, b))


_CACHE: dict[str, WarehouseContext] = {}


def get_warehouse_context(session: Session, layout_id: str) -> WarehouseContext:
    if layout_id in _CACHE:
        return _CACHE[layout_id]
    row = session.get(Warehouse, layout_id)
    if row is None:
        raise ValueError(
            f"no warehouses row for layout_id={layout_id!r} -- was this run's Warehouse row ever persisted "
            "(see cli/main.py::_run_simulation's session.merge(Warehouse(...)))?"
        )
    ctx = _build_context(layout_id, row.raw_layout_json)
    _CACHE[layout_id] = ctx
    return ctx


def clear_cache() -> None:
    """Tests build multiple small layouts under different layout_ids
    across a session-scoped fixture setup; nothing else needs this."""
    _CACHE.clear()


def _build_context(layout_id: str, layout: dict) -> WarehouseContext:
    graph = graph_from_json(layout)
    ctx = WarehouseContext(layout_id=layout_id)

    for zone in layout.get("geometry", {}).get("zones", []):
        zt = zone.get("metadata", {}).get("zone_type")
        if zt:
            ctx.zone_type_by_zone_id[zone["id"]] = zt

    n_nodes = graph.number_of_nodes()
    degree_centrality = nx.degree_centrality(graph) if n_nodes else {}
    node_degree = dict(graph.degree())
    node_shared = {n: d > 2 for n, d in node_degree.items()}
    for node, attrs in graph.nodes(data=True):
        zt = attrs.get("zone_type")
        if zt:
            ctx.zone_type_by_node[node] = zt

    edge_incidence: dict[str, set[str]] = {}
    for u, v, attrs in graph.edges(data=True):
        key = canon_edge(u, v)
        width = attrs.get("width_m") or 0.1
        traffic = attrs.get("traffic_weight", 0.0)
        degree_factor = max(node_degree.get(u, 0), node_degree.get(v, 0))
        # Same formula as warehouse_layout's graph/metrics.py::compute_metrics
        # bottleneck-candidate score -- this is that same definition applied
        # to every edge, not just the top 10 kept in derived_metrics.
        bottleneck = (traffic * degree_factor) / max(width, 0.1)
        junction = node_shared.get(u, False) or node_shared.get(v, False)
        ctx.edges[key] = EdgeContext(
            length_m=attrs.get("length_m"),
            width_m=attrs.get("width_m"),
            node_out_degree=degree_factor,
            node_centrality=max(degree_centrality.get(u, 0.0), degree_centrality.get(v, 0.0)),
            bottleneck_risk_score=round(bottleneck, 4),
            shared_edge_flag=junction,
            shared_node_flag=junction,
        )
        edge_incidence.setdefault(u, set()).add(key)
        edge_incidence.setdefault(v, set()).add(key)

    for key in ctx.edges:
        u, v = key.split("|")
        neighbors = (edge_incidence.get(u, set()) | edge_incidence.get(v, set())) - {key}
        ctx.edge_neighbors[key] = neighbors

    return ctx
