"""Flow-through / I-flow archetype (Section B): receiving and shipping on
opposite ends of the building, single directional flow between them.
Storage field sits between two zone bands (inbound wall + outbound
wall), rows run perpendicular to both walls so the picking aisles are
literally the flow path from receiving to shipping.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.schema import LayoutConfig, ZonesConfig
from fleetnet_layout.generation.archetypes.base import (
    finalize_one_way,
    opposite_wall,
    reserve_zone_band,
    sample_and_place_docks,
)
from fleetnet_layout.generation.constraints import apply_subtractive_layer, generate_column_grid
from fleetnet_layout.generation.storage import build_storage_field
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.generation.zones import pack_zone_band
from fleetnet_layout.geometry.primitives import Rect

_INBOUND = ["receiving", "staging", "picking"]
_OUTBOUND = ["shipping", "packing", "returns", "charging", "office"]


def build(rng: np.random.Generator, cfg: LayoutConfig) -> LayoutBuildResult:
    footprint = Rect(0.0, 0.0, cfg.warehouse.length_m, cfg.warehouse.width_m)
    wall = cfg.structural_constraints.dock_wall
    far_wall = opposite_wall(wall)

    zones = cfg.zones
    inbound_area = sum(getattr(zones, n).area_m2 for n in _INBOUND if getattr(zones, n).enabled)
    outbound_area = sum(getattr(zones, n).area_m2 for n in _OUTBOUND if getattr(zones, n).enabled)

    inbound_depth = max(min(inbound_area / footprint.w, footprint.h * 0.25), 6.0)
    outbound_depth = max(min(outbound_area / footprint.w, footprint.h * 0.25), 6.0)

    inbound_band, remainder = reserve_zone_band(footprint, wall, inbound_depth)
    outbound_band, storage_rect = reserve_zone_band(remainder, far_wall, outbound_depth)

    inbound_zones = pack_zone_band(inbound_band, zones, id_prefix="in", order=_INBOUND)
    outbound_zones = pack_zone_band(outbound_band, zones, id_prefix="out", order=_OUTBOUND)
    all_zones = inbound_zones.zones + outbound_zones.zones

    field = build_storage_field(rng, storage_rect, cfg.storage, cfg.aisles, id_prefix="f0")

    columns = generate_column_grid(
        rng, storage_rect, cfg.structural_constraints.column_grid_spacing_m, cfg.diversity_controls.irregularity_level
    )
    racks = apply_subtractive_layer(field.racks, columns)

    docks: list = []
    for z in all_zones:
        zt = z.metadata["zone_type"]
        if zt not in ("receiving", "shipping"):
            continue
        w = wall if zt == "receiving" else far_wall
        minx, miny, maxx, maxy = z.polygon.bounds
        zr = Rect(minx, miny, maxx - minx, maxy - miny)
        docks += sample_and_place_docks(rng, zr, w, cfg, role=zt, id_prefix=zt)

    result = LayoutBuildResult(
        footprint=footprint,
        racks=racks,
        main_aisles=field.main_aisles,
        secondary_aisles=field.secondary_aisles,
        cross_aisles=field.cross_aisles,
        zones=all_zones,
        docks=docks,
        columns=columns,
    )
    if field.main_aisles:
        result.fire_lane_ids = [field.main_aisles[len(field.main_aisles) // 2].id]
    finalize_one_way(rng, result, cfg)
    return result
