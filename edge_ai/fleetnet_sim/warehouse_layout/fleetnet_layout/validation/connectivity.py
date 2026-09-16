"""Graph connectivity checks (Section L rules 1, 6, 9-11)."""
from __future__ import annotations

import networkx as nx

from fleetnet_layout.graph import metadata as md


def check_full_connectivity(graph: nx.Graph) -> list[str]:
    if graph.number_of_nodes() == 0:
        return ["connectivity:empty_graph"]
    n_components = nx.number_connected_components(graph)
    if n_components <= 1:
        return []
    return [f"connectivity:disconnected:{n_components}_components"]


def check_zone_reachability(graph: nx.Graph) -> list[str]:
    """Every zone_entry node must have degree >= 1 (Section L rule 6)."""
    failures = []
    for node, attrs in graph.nodes(data=True):
        if attrs.get(md.NODE_ZONE_TYPE) is not None and graph.degree(node) == 0:
            failures.append(f"zone_unreachable:{attrs[md.NODE_ZONE_TYPE]}")
    return failures


def check_dead_end_length(graph: nx.Graph, max_dead_end_length_m: float) -> list[str]:
    """Section L rule 8: a dead-end *segment* longer than the configured
    max is invalid. We check the single incident edge of each degree-1
    node (its only segment) against the limit."""
    failures = []
    for node, attrs in graph.nodes(data=True):
        if not attrs.get(md.NODE_DEAD_END):
            continue
        for _, _, edge_attrs in graph.edges(node, data=True):
            length = edge_attrs.get(md.EDGE_LENGTH_M, 0.0)
            if length > max_dead_end_length_m:
                failures.append(f"dead_end_too_long:{node}:{length:.1f}m")
    return failures


def check_one_way_consistency(graph: nx.Graph) -> list[str]:
    """A one-way edge must have a declared direction; a two-way edge must
    not (Section L rule 11 — invalid one-way connectivity)."""
    failures = []
    for u, v, attrs in graph.edges(data=True):
        one_way = attrs.get(md.EDGE_ONE_WAY, False)
        direction = attrs.get(md.EDGE_DIRECTION)
        if one_way and direction not in ("forward", "backward"):
            failures.append(f"one_way_inconsistent:{u}-{v}")
        if not one_way and direction is not None:
            failures.append(f"one_way_inconsistent:{u}-{v}")
    return failures
