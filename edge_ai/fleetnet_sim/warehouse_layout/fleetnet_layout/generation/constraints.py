"""Structural constraints + the subtractive irregularity layer (Section H).

Per the research's explicit modeling recommendation: generate a clean
archetype first, then stamp exclusion polygons (columns here; fixed
rooms/fire lanes are represented as metadata for v1 — see README's
"known limitations") onto the regular grid, cutting whichever rack
polygon they land in. Only racks are ever cut (never aisles/zones) so
the walkable network never needs re-routing logic in this version —
documented as a deliberate scope simplification, not an oversight.

``irregularity_level`` controls what fraction of column-grid intersection
points actually get materialized as exclusions — 0.0 means a clean grid
with no columns cut into racks, 1.0 stamps nearly every intersection.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box

from fleetnet_layout.geometry.operations import subtract
from fleetnet_layout.geometry.primitives import GeoObject, Rect


def generate_column_grid(
    rng: np.random.Generator,
    footprint: Rect,
    spacing_m: float | None,
    irregularity_level: float,
    column_size_m: float = 0.5,
) -> list[GeoObject]:
    if not spacing_m or spacing_m <= 0:
        return []
    columns: list[GeoObject] = []
    xs = np.arange(spacing_m, footprint.w, spacing_m)
    ys = np.arange(spacing_m, footprint.h, spacing_m)
    materialize_p = 0.15 + 0.8 * irregularity_level
    idx = 0
    for x in xs:
        for y in ys:
            if rng.random() > materialize_p:
                continue
            r = Rect(footprint.x + float(x) - column_size_m / 2, footprint.y + float(y) - column_size_m / 2, column_size_m, column_size_m)
            columns.append(GeoObject(id=f"column_{idx}", kind="exclusion", polygon=r.to_polygon(), metadata={"exclusion_type": "column"}))
            idx += 1
    return columns


def apply_subtractive_layer(racks: list[GeoObject], exclusions: list[GeoObject]) -> list[GeoObject]:
    """Cut each exclusion polygon out of any rack it overlaps. If a cut
    splits a rack into multiple pieces, keep only the largest piece
    (small slivers are dropped) — see module docstring for rationale."""
    if not exclusions:
        return racks
    result: list[GeoObject] = []
    for rack in racks:
        poly: Polygon | MultiPolygon = rack.polygon
        touched = False
        for excl in exclusions:
            if poly.intersects(excl.polygon) and poly.intersection(excl.polygon).area > 1e-9:
                poly = subtract(poly, excl.polygon)
                touched = True
        if not touched:
            result.append(rack)
            continue
        if poly.is_empty:
            continue
        if isinstance(poly, MultiPolygon):
            largest = max(poly.geoms, key=lambda g: g.area)
            poly = largest
        rack.polygon = poly
        rack.metadata["notched_by_column"] = True
        result.append(rack)
    return result
