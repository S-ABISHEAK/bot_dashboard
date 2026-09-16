"""Shared helpers used by every archetype builder.

Each archetype module exposes a single ``build(rng, cfg) ->
LayoutBuildResult`` function (a functional registry in
``generation.generator`` dispatches on ``cfg.warehouse.archetype``,
rather than a class hierarchy — there is no per-archetype *state* to
share, only *functions*, so a plain module-level callable is simpler
than an ABC with one concrete method). This module holds the logic every
archetype leans on: zone-band reservation against a wall, the rack/aisle
field builder call, column-grid generation + the subtractive layer, and
one-way assignment.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.enums import DockWall
from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.aisles import assign_one_way
from fleetnet_layout.generation.constraints import apply_subtractive_layer, generate_column_grid
from fleetnet_layout.generation.docks import place_docks, sample_dock_door_count
from fleetnet_layout.generation.storage import build_storage_field
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.generation.zones import pack_zone_band
from fleetnet_layout.geometry.primitives import Rect

# Shared inbound/outbound zone split used by every archetype that places
# receiving and shipping on opposite walls (grid, flow_through,
# zone_based, u_flow, l_flow) -- see reserve_zone_band's docstring and
# grid.py's module docstring for why opposite walls matter for routing.
INBOUND_ZONES = ["receiving", "staging", "picking"]
OUTBOUND_ZONES = ["shipping", "packing", "returns", "charging", "office"]


def reserve_zone_band(footprint: Rect, wall: DockWall, depth_m: float) -> tuple[Rect, Rect]:
    """Split the footprint into a zone band against ``wall`` (depth
    ``depth_m``) and the remaining interior rect. Only north/south are
    supported by the current zone/dock packers (see docks.py docstring);
    east/west archetypes rotate the footprint before calling this and
    rotate the result back (see l_flow.py once implemented)."""
    if wall == DockWall.SOUTH:
        band = Rect(footprint.x, footprint.y, footprint.w, depth_m)
        rest = Rect(footprint.x, footprint.y + depth_m, footprint.w, footprint.h - depth_m)
    elif wall == DockWall.NORTH:
        band = Rect(footprint.x, footprint.y + footprint.h - depth_m, footprint.w, depth_m)
        rest = Rect(footprint.x, footprint.y, footprint.w, footprint.h - depth_m)
    elif wall == DockWall.WEST:
        band = Rect(footprint.x, footprint.y, depth_m, footprint.h)
        rest = Rect(footprint.x + depth_m, footprint.y, footprint.w - depth_m, footprint.h)
    else:  # EAST
        band = Rect(footprint.x + footprint.w - depth_m, footprint.y, depth_m, footprint.h)
        rest = Rect(footprint.x, footprint.y, footprint.w - depth_m, footprint.h)
    return band, rest


def opposite_wall(wall: DockWall) -> DockWall:
    return {
        DockWall.SOUTH: DockWall.NORTH,
        DockWall.NORTH: DockWall.SOUTH,
        DockWall.EAST: DockWall.WEST,
        DockWall.WEST: DockWall.EAST,
    }[wall]


def adjacent_wall(wall: DockWall) -> DockWall:
    return {
        DockWall.SOUTH: DockWall.EAST,
        DockWall.EAST: DockWall.SOUTH,
        DockWall.NORTH: DockWall.WEST,
        DockWall.WEST: DockWall.NORTH,
    }[wall]


def build_columns_and_notch(rng: np.random.Generator, footprint: Rect, cfg: LayoutConfig, racks: list) -> list:
    columns = generate_column_grid(
        rng, footprint, cfg.structural_constraints.column_grid_spacing_m, cfg.diversity_controls.irregularity_level
    )
    return columns


def finalize_one_way(rng: np.random.Generator, result: LayoutBuildResult, cfg: LayoutConfig) -> None:
    assign_one_way(rng, result.secondary_aisles + result.cross_aisles, cfg.aisles.one_way_ratio)


def sample_and_place_docks(rng, zone_band_rect: Rect, wall: DockWall, cfg: LayoutConfig, role: str, id_prefix: str, min_doors: int = 1) -> list:
    band = cfg.warehouse
    door_count = sample_dock_door_count(rng, cfg.warehouse.area_m2 / 2, min_doors, 30)
    placement = place_docks(rng, zone_band_rect, wall, door_count, role, id_prefix)
    return placement.docks
