"""Dual-egress check (Section L rule 2, Section W).

"Deepest interior point" is approximated by walking inward from every
dead-end node to its nearest *real* junction (degree >= 3) — testing the
dead-end node itself would be meaningless, since a degree-1 node can
never have more than one vertex-disjoint path to anywhere (Menger's
theorem caps disjoint paths at the minimum degree of the two endpoints);
every picking-aisle dead end would trivially "fail" a check applied to
itself. What the spec actually cares about is whether, once you're back
at a real branch point, there are two independent routes onward to an
exit — that's the node this check tests.

"Exit" nodes are the receiving/shipping zone_entry nodes (the only
points the graph treats as connections to the outside world in this
version — see docks.py's module docstring for why docks aren't separate
graph nodes). Implemented as vertex-disjoint-paths counting (Menger's
theorem) via a virtual supersink connected to every exit node.

Capped to a bounded number of junctions (``max_checks``) so a single
validation pass stays fast on large graphs — ``node_connectivity`` is a
max-flow computation per call, and a very large/very_large warehouse can
have hundreds of dead ends sharing only a handful of distinct junctions.
"""
from __future__ import annotations

import networkx as nx

from fleetnet_layout.graph import metadata as md

_EXIT_ZONE_TYPES = ("receiving", "shipping")
_SUPERSINK = "__egress_supersink__"


def _nearest_junction(graph: nx.Graph, dead_end: str) -> str | None:
    """Walk from a degree-1 node through degree-2 pass-through nodes until
    a real branch point (degree >= 3) or an exit is found."""
    prev, cur = None, dead_end
    for _ in range(graph.number_of_nodes() + 1):
        neighbors = [n for n in graph.neighbors(cur) if n != prev]
        if not neighbors:
            return None
        nxt = neighbors[0]
        degree = graph.degree(nxt)
        if degree != 2 or graph.nodes[nxt].get(md.NODE_ZONE_TYPE) is not None:
            return nxt
        prev, cur = cur, nxt
    return None


def check_dual_egress(graph: nx.Graph, required_paths: int = 2, max_checks: int = 25) -> list[str]:
    if graph.number_of_nodes() == 0:
        return []

    exit_nodes = [n for n, a in graph.nodes(data=True) if a.get(md.NODE_ZONE_TYPE) in _EXIT_ZONE_TYPES]
    if not exit_nodes:
        return ["egress:no_exit_zones"]

    dead_ends = [n for n, a in graph.nodes(data=True) if a.get(md.NODE_DEAD_END) and n not in exit_nodes]
    if not dead_ends:
        return []

    junctions: set[str] = set()
    for node in dead_ends:
        j = _nearest_junction(graph, node)
        if j is not None and j not in exit_nodes:
            junctions.add(j)
        if len(junctions) >= max_checks:
            break

    if not junctions:
        return []

    g2 = graph.copy()
    g2.add_node(_SUPERSINK)
    for e in exit_nodes:
        g2.add_edge(e, _SUPERSINK)

    failures = []
    for node in junctions:
        if not nx.has_path(g2, node, _SUPERSINK):
            failures.append(f"egress_unreachable:{node}")
            continue
        try:
            connectivity = nx.node_connectivity(g2, node, _SUPERSINK)
        except nx.NetworkXError:
            connectivity = 0
        if connectivity < required_paths:
            failures.append(f"insufficient_egress_paths:{node}:{connectivity}")
    return failures
