"""Walkable-space union: aisles + zone access strips, minus exclusions.

This is the input to ``graph.builder`` (Section M's pipeline: geometry ->
walkable space -> centerline/intersection graph). We don't literally
skeletonize a rasterized union (expensive, and unnecessary given our
aisles are already axis-aligned rectangles from an explicit grid) —
instead ``graph.builder`` extracts intersections directly from the known
rectangle adjacency, which is simpler and exact for orthogonal
archetypes. This module still provides the union polygon for
visualization and for a generic reachability sanity-check independent of
the graph extraction logic.
"""
from __future__ import annotations

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from fleetnet_layout.geometry.primitives import GeoObject


def walkable_union(aisles: list[GeoObject], zones: list[GeoObject]) -> BaseGeometry:
    polys = [a.polygon for a in aisles] + [z.polygon for z in zones]
    if not polys:
        from shapely.geometry import Polygon

        return Polygon()
    return unary_union(polys)
