"""Derived metrics from the finished navigation graph (Section M/T).

``bottleneck_candidates`` is computed here and ONLY here — see the
plan's design decision #1: an edge's bottleneck score is
traffic_weight / effective_width, i.e. how much projected flow is
squeezed through how little space, relative to its neighborhood. No
archetype, preset, or config field is ever allowed to author a
bottleneck directly; this module is the single source of that label.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from fleetnet_layout.graph import metadata as md


@dataclass
class DerivedMetrics:
    aisle_count: int
    intersection_count: int
    dead_end_count: int
    storage_density: float
    bottleneck_candidates: list[dict] = field(default_factory=list)
    graph_diameter: int | None = None
    average_path_length: float | None = None
    connected_components: int = 0
    aspect_ratio: float = 0.0


def compute_metrics(graph: nx.Graph, storage_density: float, aspect_ratio: float, top_n_bottlenecks: int = 10) -> DerivedMetrics:
    intersection_count = sum(1 for _, a in graph.nodes(data=True) if a.get(md.NODE_TYPE) == "intersection")
    dead_end_count = sum(1 for _, a in graph.nodes(data=True) if a.get(md.NODE_DEAD_END))
    aisle_count = graph.number_of_edges()

    n_components = nx.number_connected_components(graph) if graph.number_of_nodes() else 0
    diameter = None
    avg_path = None
    if n_components == 1 and graph.number_of_nodes() > 1:
        try:
            diameter = nx.diameter(graph)
            avg_path = nx.average_shortest_path_length(graph, weight=md.EDGE_LENGTH_M)
        except nx.NetworkXError:
            pass

    scored = []
    for u, v, attrs in graph.edges(data=True):
        width = attrs.get(md.EDGE_WIDTH_M) or 0.1
        traffic = attrs.get(md.EDGE_TRAFFIC_WEIGHT, 0.0)
        degree_factor = max(graph.degree(u), graph.degree(v))
        score = (traffic * degree_factor) / max(width, 0.1)
        scored.append({"edge": [u, v], "score": round(score, 4), "width_m": width, "traffic_weight": traffic})
    scored.sort(key=lambda x: x["score"], reverse=True)

    return DerivedMetrics(
        aisle_count=aisle_count,
        intersection_count=intersection_count,
        dead_end_count=dead_end_count,
        storage_density=storage_density,
        bottleneck_candidates=scored[:top_n_bottlenecks],
        graph_diameter=diameter,
        average_path_length=avg_path,
        connected_components=n_components,
        aspect_ratio=aspect_ratio,
    )
