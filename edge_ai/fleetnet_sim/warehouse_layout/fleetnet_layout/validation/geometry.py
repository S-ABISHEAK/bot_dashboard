"""Geometric validity checks (Section L rules 3, 5, 7).

Overlap is checked only between non-aisle objects (racks, zones,
exclusions) — Section L rule 3 explicitly scopes the overlap check to
"any rack block, zone, or exclusion polygon intersects another
non-aisle polygon," which exempts aisle-aisle and aisle-exclusion
overlap by design (a column can sit inside an aisle, narrowing it,
without being an invalid layout; docks are excluded entirely — see
``generation.docks``'s module docstring for why).
"""
from __future__ import annotations

from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.geometry.operations import any_overlap, within_boundary


def check_no_illegal_overlap(result: LayoutBuildResult) -> list[str]:
    non_aisle_objects = result.racks + result.zones + result.all_exclusions
    pairs = any_overlap(non_aisle_objects)
    return [f"overlap:{a}:{b}" for a, b in pairs]


def check_within_boundary(result: LayoutBuildResult) -> list[str]:
    fp = result.footprint.to_polygon()
    all_objects = result.racks + result.zones + result.all_aisles + result.docks + result.all_exclusions
    return [f"out_of_bounds:{o.id}" for o in all_objects if not within_boundary(o.polygon, fp)]
