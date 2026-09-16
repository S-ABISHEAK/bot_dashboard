"""Dock door count/spacing/geometry (Section Q).

Docks are modeled as thin apron markers along the dock wall, nested
inside the receiving/shipping zone band rather than as independent
floor-area competitors — real dock aprons/staging lanes *are* the
receiving/shipping zone, so a dock's polygon is deliberately allowed to
sit inside its owning zone's polygon (excluded from the general
non-aisle overlap check in ``validation.geometry``, which is documented
there). What matters for the navigation graph is the dock's *access
point* on the wall, which ``graph.builder`` turns into a node.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fleetnet_layout.config.defaults import DOCK_AREA_PER_DOOR_M2, DOCK_DOOR_SPACING_M
from fleetnet_layout.config.distributions import poisson_in_range
from fleetnet_layout.config.enums import DockWall
from fleetnet_layout.geometry.primitives import GeoObject, Rect


def sample_dock_door_count(rng: np.random.Generator, footprint_area_m2: float, min_doors: int, max_doors: int) -> int:
    mean = footprint_area_m2 / DOCK_AREA_PER_DOOR_M2
    return poisson_in_range(rng, min_doors, max_doors, mean=mean)


@dataclass
class DockPlacement:
    docks: list[GeoObject]


def place_docks(
    rng: np.random.Generator,
    zone_rect: Rect,
    wall: DockWall,
    door_count: int,
    role: str,
    id_prefix: str,
) -> DockPlacement:
    """Place ``door_count`` dock doors as small apron rectangles along the
    zone's outer edge (the wall-facing edge of zone_rect)."""
    docks: list[GeoObject] = []
    if door_count <= 0:
        return DockPlacement(docks=docks)

    door_w = min(3.0, zone_rect.w / max(door_count, 1))
    span = door_count * DOCK_DOOR_SPACING_M
    start_offset = max((zone_rect.w - span) / 2.0, 0.0)

    for i in range(door_count):
        cx = zone_rect.x + start_offset + i * DOCK_DOOR_SPACING_M + door_w / 2.0
        cx = min(max(cx, zone_rect.x + door_w / 2.0), zone_rect.x + zone_rect.w - door_w / 2.0)
        depth = min(1.0, zone_rect.h)
        if wall in (DockWall.SOUTH,):
            r = Rect(cx - door_w / 2.0, zone_rect.y, door_w, depth)
        elif wall in (DockWall.NORTH,):
            r = Rect(cx - door_w / 2.0, zone_rect.y + zone_rect.h - depth, door_w, depth)
        elif wall == DockWall.WEST:
            r = Rect(zone_rect.x, cx - door_w / 2.0, depth, door_w)
        else:  # EAST
            r = Rect(zone_rect.x + zone_rect.w - depth, cx - door_w / 2.0, depth, door_w)
        docks.append(
            GeoObject(
                id=f"dock_{id_prefix}_{i}",
                kind="dock",
                polygon=r.to_polygon(),
                metadata={"wall": wall.value, "role": role, "door_index": i},
            )
        )
    return DockPlacement(docks=docks)
