"""Zone-based / multi-block archetype (Section B): the building is
divided into independently-organized storage sub-zones, each with its
own micro-layout, connected by a shared main spine.

Implemented by splitting the storage field into 2-4 side-by-side
sub-fields (each an independent ``build_storage_field`` call over its
own slice of the block axis, with its own row-count share and rack
type), rather than a single uniform field like `grid`. Because each
sub-field's own mandatory front/back spine (see
``generation.storage``'s module docstring) spans exactly its slice's
width and the slices are placed edge-to-edge with no gap, the spines
naturally concatenate into one continuous connector across all
sub-zones — no extra wiring needed for cross-sub-zone connectivity.

Like `grid.py`, zones are split into an inbound band (receiving/staging/
picking) against the dock wall and an outbound band (shipping/packing/
returns/charging/office) against the opposite wall, with the sub-zone
storage field sandwiched between them, so cross-zone tasks actually
route through the storage aisles instead of staying inside one band.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.enums import RackType
from fleetnet_layout.config.schema import LayoutConfig, StorageConfig
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

_SUBZONE_RACK_VARIANTS = [RackType.SELECTIVE, RackType.SHELVING, RackType.BULK_FLOOR, RackType.HIGH_DENSITY]
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
    zone_result_zones = inbound_zones.zones + outbound_zones.zones

    n_sub = max(2, min(4, cfg.storage.block_count))
    sub_width = storage_rect.w / n_sub
    rows_per_sub = max(1, cfg.storage.rack_row_count // n_sub)
    blocks_per_sub = max(1, cfg.storage.block_count // n_sub)

    all_racks, all_main, all_sec, all_cross = [], [], [], []
    for i in range(n_sub):
        sub_rect = Rect(storage_rect.x + i * sub_width, storage_rect.y, sub_width, storage_rect.h)
        sub_storage_cfg = StorageConfig(
            block_count=blocks_per_sub,
            rack_type=_SUBZONE_RACK_VARIANTS[i % len(_SUBZONE_RACK_VARIANTS)],
            rack_row_count=rows_per_sub,
            rack_orientation=cfg.storage.rack_orientation,
            storage_density=cfg.storage.storage_density,
        )
        field = build_storage_field(rng, sub_rect, sub_storage_cfg, cfg.aisles, id_prefix=f"sz{i}")
        for r in field.racks:
            r.metadata["subzone_index"] = i
        all_racks += field.racks
        all_main += field.main_aisles
        all_sec += field.secondary_aisles
        all_cross += field.cross_aisles

    columns = generate_column_grid(
        rng, storage_rect, cfg.structural_constraints.column_grid_spacing_m, cfg.diversity_controls.irregularity_level
    )
    racks = apply_subtractive_layer(all_racks, columns)

    docks: list = []
    for z in zone_result_zones:
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
        main_aisles=all_main,
        secondary_aisles=all_sec,
        cross_aisles=all_cross,
        zones=zone_result_zones,
        docks=docks,
        columns=columns,
    )
    spines = [a.id for a in all_cross if a.metadata.get("spine")]
    if spines:
        result.fire_lane_ids = spines[:1]
    finalize_one_way(rng, result, cfg)
    return result
