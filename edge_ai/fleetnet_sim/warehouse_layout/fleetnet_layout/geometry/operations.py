"""Shared geometry checks used by generation and validation.

Kept archetype-agnostic and validation-agnostic: these are pure
functions over Shapely geometry with no knowledge of config or the
navigation graph, so both ``generation.*`` (while placing objects) and
``validation.*`` (while gating a finished layout) can call the same
logic instead of duplicating overlap/clearance math.
"""
from __future__ import annotations

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from fleetnet_layout.geometry.primitives import GeoObject


def overlaps(a: BaseGeometry, b: BaseGeometry, tolerance: float = 1e-6) -> bool:
    """True if a and b share more than a touching boundary (area > tolerance)."""
    if not a.intersects(b):
        return False
    inter = a.intersection(b)
    return inter.area > tolerance


def any_overlap(objects: list[GeoObject]) -> list[tuple[str, str]]:
    """Return id pairs of objects whose polygons overlap by more than a
    touching boundary. O(n^2) — fine at per-layout object counts (tens to
    low hundreds); revisit with an STRtree if archetypes grow much larger."""
    from shapely.strtree import STRtree

    if len(objects) < 2:
        return []
    polys = [o.polygon for o in objects]
    tree = STRtree(polys)
    seen: set[tuple[int, int]] = set()
    pairs: list[tuple[str, str]] = []
    for i, poly in enumerate(polys):
        for j in tree.query(poly):
            j = int(j)
            if j == i:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            if overlaps(poly, polys[j]):
                pairs.append((objects[i].id, objects[j].id))
    return pairs


def within_boundary(obj_poly: Polygon, footprint: Polygon, tolerance: float = 1e-6) -> bool:
    """True if obj_poly is fully inside footprint (allowing for float slop)."""
    if footprint.contains(obj_poly):
        return True
    diff = obj_poly.difference(footprint)
    return diff.area <= tolerance


def min_gap(a: Polygon, b: Polygon) -> float:
    """Minimum distance between two polygons (0 if touching/overlapping)."""
    return float(a.distance(b))


def subtract(base: Polygon, cut: Polygon):
    """Subtractive-constraint helper (Section H): base minus cut, used to
    carve exclusion polygons (columns, fixed rooms, fire lanes) out of
    storage/aisle geometry. Returns a (Multi)Polygon; callers must handle
    the possibility of a MultiPolygon result (a cut can split a region)."""
    return base.difference(cut)
