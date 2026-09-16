"""Geometry -> navigation graph (Section M).

Every archetype in this package produces axis-aligned rectangular
aisles from an explicit grid construction, so rather than rasterizing +
skeletonizing the walkable-space union (expensive and lossy), we extract
the graph directly and exactly from rectangle adjacency:

  1. For every pair of aisle rectangles, find where they touch or
     overlap (a shared edge or corner-region) -> a *junction point*.
  2. Each aisle's own long axis accumulates junction points from every
     aisle it touches, plus its own two physical ends. Sorted along the
     axis and de-duplicated (snap tolerance), consecutive points become
     one graph edge each — this is exactly Section M's "aisle segments
     between two nodes."
  3. A junction point touched by only one aisle-end (no neighbor) is a
     dead end (degree 1); a point touched by 3+ aisle-ends is an
     intersection.
  4. Zones attach one "zone_entry" node (at the zone centroid) per
     enabled zone, edged to the nearest junction point on an aisle that
     touches the zone's boundary. Docks attach as metadata (dock ids)
     on the zone_entry node of their role (receiving/shipping) rather
     than as separate graph nodes — see docks.py's module docstring for
     why dock geometry doesn't compete for its own floor area.
"""
from __future__ import annotations

import math

import networkx as nx

from fleetnet_layout.config.enums import NodeType
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.geometry.primitives import GeoObject
from fleetnet_layout.graph import metadata as md

_SNAP = 0.05


def _snap_key(x: float, y: float) -> tuple[float, float]:
    return (round(x / _SNAP) * _SNAP, round(y / _SNAP) * _SNAP)


def _node_id(key: tuple[float, float]) -> str:
    """Stable string node id derived from a snapped (x, y) — string ids
    (not raw coordinate tuples) keep the JSON graph export unambiguous
    and match Section AI's "everything has a stable id" requirement."""
    return f"n_{key[0]:.2f}_{key[1]:.2f}"


def _axis_and_bounds(obj: GeoObject) -> tuple[str, float, float, float, float]:
    minx, miny, maxx, maxy = obj.polygon.bounds
    w, h = maxx - minx, maxy - miny
    axis = "x" if w >= h else "y"
    return axis, minx, miny, maxx, maxy


_TOUCH_TOLERANCE = 1e-6


def _touch_point(a: GeoObject, b: GeoObject) -> tuple[float, float] | None:
    """Touch/overlap centroid between two aisle rectangles, tolerant of
    sub-micrometer floating-point gaps: adjacent aisle segments are built
    from a shared cursor accumulation (see ``generation.aisles.fit_segments``)
    whose additions aren't perfectly associative, so two rectangles meant
    to share an exact edge can end up ~1e-13 apart. A hard ``intersects()``
    check would misclassify that as no touch at all (a silent
    connectivity bug, not just a cosmetic one) — so we fall back to
    nearest-points when the exact intersection is empty but the gap is
    within tolerance."""
    if a.polygon.intersects(b.polygon):
        inter = a.polygon.intersection(b.polygon)
        if not inter.is_empty:
            c = inter.centroid
            return (float(c.x), float(c.y))
    if a.polygon.distance(b.polygon) <= _TOUCH_TOLERANCE:
        from shapely.ops import nearest_points

        p1, p2 = nearest_points(a.polygon, b.polygon)
        return ((p1.x + p2.x) / 2.0, (p1.y + p2.y) / 2.0)
    return None


def build_navigation_graph(result: LayoutBuildResult) -> nx.Graph:
    graph = nx.Graph()
    aisles = result.all_aisles
    if not aisles:
        return graph

    # Touch detection (aisle-aisle) via an STRtree spatial index: query
    # each aisle's slightly-buffered envelope for neighbor candidates
    # instead of an O(n^2) full scan, which matters once aisle counts
    # reach the hundreds (large/very_large scale classes).
    from shapely.strtree import STRtree

    polys = [a.polygon for a in aisles]
    tree = STRtree(polys)
    touches: dict[str, set[tuple[float, float]]] = {a.id: set() for a in aisles}
    seen_pairs: set[tuple[int, int]] = set()
    for i, poly in enumerate(polys):
        candidates = tree.query(poly.buffer(_TOUCH_TOLERANCE * 10))
        for j in candidates:
            j = int(j)
            if j <= i:
                continue
            key_pair = (i, j)
            if key_pair in seen_pairs:
                continue
            seen_pairs.add(key_pair)
            a, b = aisles[i], aisles[j]
            pt = _touch_point(a, b)
            if pt is None:
                continue
            key = _snap_key(*pt)
            touches[a.id].add(key)
            touches[b.id].add(key)

    node_positions: dict[str, tuple[float, float]] = {}

    def register_node(key: tuple[float, float]) -> str:
        nid = _node_id(key)
        node_positions.setdefault(nid, key)
        return nid

    edges_to_add: list[tuple[str, str, GeoObject]] = []

    for a in aisles:
        axis, minx, miny, maxx, maxy = _axis_and_bounds(a)
        pts = set(touches[a.id])
        if axis == "x":
            end_lo = (minx, (miny + maxy) / 2)
            end_hi = (maxx, (miny + maxy) / 2)
        else:
            end_lo = ((minx + maxx) / 2, miny)
            end_hi = ((minx + maxx) / 2, maxy)
        pts.add(_snap_key(*end_lo))
        pts.add(_snap_key(*end_hi))

        ordered = sorted(pts, key=lambda k: k[0] if axis == "x" else k[1])
        ordered_ids = [register_node(k) for k in ordered]
        for k1, k2 in zip(ordered_ids, ordered_ids[1:]):
            edges_to_add.append((k1, k2, a))

    for nid, xy in node_positions.items():
        graph.add_node(
            nid,
            **{
                md.NODE_TYPE: NodeType.WAYPOINT.value,
                md.NODE_X: xy[0],
                md.NODE_Y: xy[1],
                md.NODE_DEAD_END: False,
                md.NODE_ZONE_TYPE: None,
                md.NODE_DOCK_IDS: [],
            },
        )

    for k1, k2, aisle in edges_to_add:
        if k1 == k2:
            continue
        x1, y1 = node_positions[k1]
        x2, y2 = node_positions[k2]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1e-6:
            continue
        role = aisle.metadata.get("archetype_role", "secondary")
        one_way = bool(aisle.metadata.get("one_way", False))
        if graph.has_edge(k1, k2):
            existing = graph[k1][k2]
            existing.setdefault(md.EDGE_SOURCE_IDS, []).append(aisle.id)
            continue
        graph.add_edge(
            k1,
            k2,
            **{
                md.EDGE_LENGTH_M: length,
                md.EDGE_WIDTH_M: aisle.metadata.get("width_m"),
                md.EDGE_WIDTH_CLASS: aisle.metadata.get("width_class"),
                md.EDGE_ONE_WAY: one_way,
                md.EDGE_DIRECTION: aisle.metadata.get("direction") if one_way else None,
                md.EDGE_ARCHETYPE_ROLE: role,
                md.EDGE_TRAFFIC_WEIGHT: _base_traffic_weight(role),
                md.EDGE_SOURCE_IDS: [aisle.id],
                md.EDGE_TRAVERSABLE: True,
            },
        )

    _attach_zones(graph, result)
    _finalize_node_types(graph)
    return graph


def _finalize_node_types(graph: nx.Graph) -> None:
    """Degree-based node classification, run once *after* zone/dock
    attachment so a waypoint that only gained a neighbor via a
    zone_access edge is correctly reclassified out of dead-end."""
    for node, attrs in graph.nodes(data=True):
        if attrs.get(md.NODE_TYPE) == NodeType.ZONE_ENTRY.value:
            continue
        degree = graph.degree(node)
        if degree <= 1:
            attrs[md.NODE_DEAD_END] = True
            attrs[md.NODE_TYPE] = NodeType.DEAD_END.value
        else:
            attrs[md.NODE_DEAD_END] = False
            attrs[md.NODE_TYPE] = NodeType.INTERSECTION.value if degree >= 3 else NodeType.WAYPOINT.value


_ROLE_BASE_TRAFFIC = {
    "main": 0.8,
    "spine": 0.9,
    "cross": 0.5,
    "secondary": 0.3,
    "feeder": 0.4,
    "dock_apron": 0.7,
    "zone_access": 0.6,
}


def _base_traffic_weight(role: str) -> float:
    return _ROLE_BASE_TRAFFIC.get(role, 0.3)


def _nearest_node_touching(graph: nx.Graph, zone: GeoObject, aisles: list[GeoObject]) -> str | None:
    best_key = None
    best_dist = float("inf")
    for a in aisles:
        if not a.polygon.intersects(zone.polygon):
            continue
        # find graph nodes that lie on this aisle's footprint
        for node, attrs in graph.nodes(data=True):
            p = (attrs[md.NODE_X], attrs[md.NODE_Y])
            from shapely.geometry import Point

            if a.polygon.buffer(1e-6).contains(Point(p)) or a.polygon.exterior.distance(Point(p)) < 1e-3:
                zc = zone.polygon.centroid
                d = math.hypot(p[0] - zc.x, p[1] - zc.y)
                if d < best_dist:
                    best_dist = d
                    best_key = node
    return best_key


def _attach_zones(graph: nx.Graph, result: LayoutBuildResult) -> None:
    aisles = result.all_aisles
    docks_by_role: dict[str, list[str]] = {}
    for d in result.docks:
        docks_by_role.setdefault(d.metadata.get("role", ""), []).append(d.id)

    for zone in result.zones:
        zt = zone.metadata["zone_type"]
        node_key = f"zone_{zt}"
        c = zone.polygon.centroid
        graph.add_node(
            node_key,
            **{
                md.NODE_TYPE: NodeType.ZONE_ENTRY.value,
                md.NODE_X: float(c.x),
                md.NODE_Y: float(c.y),
                md.NODE_DEAD_END: False,
                md.NODE_ZONE_TYPE: zt,
                md.NODE_DOCK_IDS: docks_by_role.get(zt, []),
            },
        )
        anchor = _nearest_node_touching(graph, zone, aisles)
        if anchor is None:
            continue
        ax, ay = graph.nodes[anchor][md.NODE_X], graph.nodes[anchor][md.NODE_Y]
        length = math.hypot(float(c.x) - ax, float(c.y) - ay)
        graph.add_edge(
            node_key,
            anchor,
            **{
                md.EDGE_LENGTH_M: max(length, 0.1),
                md.EDGE_WIDTH_M: 2.0,
                md.EDGE_WIDTH_CLASS: "standard",
                md.EDGE_ONE_WAY: False,
                md.EDGE_DIRECTION: None,
                md.EDGE_ARCHETYPE_ROLE: "zone_access",
                md.EDGE_TRAFFIC_WEIGHT: _base_traffic_weight("zone_access"),
                md.EDGE_SOURCE_IDS: [zone.id],
                md.EDGE_TRAVERSABLE: True,
            },
        )
        graph.nodes[anchor][md.NODE_DEAD_END] = False
