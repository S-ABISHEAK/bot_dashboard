"""Rack-block + aisle-grid field builder — the shared base grammar
(Section D/I: racks first, aisles as negative space, cross-aisles at
interval) reused by the grid/flow_through/u_flow/l_flow/central_corridor
archetypes.

Given a rectangular "storage field" (the footprint area left over after
zones/margins are carved out) and rack_orientation, this lays out:
  - block_count blocks along the "block axis", separated by main aisles
  - rack_row_count rows (distributed evenly across blocks) along the
    same axis within each block, separated by secondary aisles
  - cross-aisles along the "depth axis" at ~cross_aisle_interval_m,
    cutting every row/aisle into travel segments so no aisle exceeds the
    configured interval without a cross-connection

``rack_orientation=perpendicular_to_dock`` means rows run along the
depth axis (deep into the building, away from the dock wall) with
picking aisles alongside them — the standard pallet-DC layout.

KNOWN LIMITATION (v1): the depth axis here is always the rect's own
y-extent, which by construction is the direction that connects to the
dock-wall zone band (``archetypes.base.reserve_zone_band`` always splits
along y for the north/south walls the sampler currently restricts to —
see ``generation.sampling``'s dock_wall comment). A true axis swap for
``parallel_to_dock`` (rows long in x, blocks stacked in y) was tried and
rejected: it transposes which physical axis is "depth," but the zone
band's location doesn't rotate with it, so the spine meant to connect
rows to the dock band ends up on the wrong wall and orphans every zone
that isn't at a field corner. Until the zone/dock system is made
orientation-aware, ``rack_orientation`` is honored as metadata on every
rack object (for downstream consumers / future revisions) but does not
change the physical grid topology — every field is generated in the
perpendicular_to_dock arrangement.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import box

from fleetnet_layout.config.defaults import RACK_ROW_DEPTH_M
from fleetnet_layout.config.enums import ArchetypeRole, RackOrientation
from fleetnet_layout.config.schema import AislesConfig, StorageConfig
from fleetnet_layout.generation.aisles import AxisSegments, fit_segments
from fleetnet_layout.generation.sampling import aisle_width_m
from fleetnet_layout.geometry.primitives import GeoObject, Rect


@dataclass
class FieldResult:
    racks: list[GeoObject]
    main_aisles: list[GeoObject]
    secondary_aisles: list[GeoObject]
    cross_aisles: list[GeoObject]
    main_width_m: float
    secondary_width_m: float


def build_storage_field(
    rng: np.random.Generator,
    rect: Rect,
    storage_cfg: StorageConfig,
    aisles_cfg: AislesConfig,
    id_prefix: str = "f0",
) -> FieldResult:
    # See module docstring's "KNOWN LIMITATION" note: the physical grid is
    # always built perpendicular_to_dock-style (block axis = x, depth
    # axis = y, matching the zone band's fixed orientation); the
    # configured rack_orientation is preserved as rack metadata only.
    perpendicular = True
    block_axis_len = rect.w
    depth_axis_len = rect.h

    main_w = aisle_width_m(rng, aisles_cfg.main_width_class)
    secondary_w = aisle_width_m(rng, aisles_cfg.secondary_width_class)

    blocks = fit_segments(
        block_axis_len, storage_cfg.block_count, item_size=max(block_axis_len / max(storage_cfg.block_count, 1), RACK_ROW_DEPTH_M), gap_size=main_w
    )
    # Floored at 2, not 1: fit_segments(target_count=1) always returns a
    # single segment with no internal gap, so a block with rows_per_block
    # == 1 gets zero secondary aisles -- picking tasks then have nowhere
    # to route through and fall back to the raw zone band (see
    # TaskGenerator._cells_for). At least 2 guarantees >= 1 gap per block.
    rows_per_block = max(2, storage_cfg.rack_row_count // max(blocks.count, 1))

    # Spine aisles run along BOTH ends of the depth axis, connecting
    # every picking aisle to the main network regardless of which end
    # the dock wall's zone band sits against (near end for south/west,
    # far end for north/east — this module doesn't know which, so both
    # ends get one). This also guarantees connectivity when
    # block_count==1 (no between-block main aisles) and/or the field is
    # too shallow for more than one cross-aisle segment, which otherwise
    # produces parallel, mutually disconnected picking aisles.
    front_spine_w = min(main_w, depth_axis_len * 0.2)
    back_spine_w = min(main_w, depth_axis_len * 0.2)
    remaining_depth = max(depth_axis_len - front_spine_w - back_spine_w, 1.0)

    cross_target = max(1, round(remaining_depth / max(aisles_cfg.cross_aisle_interval_m, 1.0)))
    cross_w = min(secondary_w, 2.4)
    depth_segments = fit_segments(remaining_depth, cross_target, item_size=aisles_cfg.cross_aisle_interval_m, gap_size=cross_w)
    depth_segments = AxisSegments(
        count=depth_segments.count,
        item_size=depth_segments.item_size,
        gap_size=depth_segments.gap_size,
        item_starts=tuple(s + front_spine_w for s in depth_segments.item_starts),
    )

    def make_rect(x: float, y: float, w: float, h: float) -> Rect:
        return Rect(rect.x + x, rect.y + y, w, h) if perpendicular else Rect(rect.x + y, rect.y + x, h, w)

    racks: list[GeoObject] = []
    secondary_aisles: list[GeoObject] = []

    for bi, block_start in enumerate(blocks.item_starts):
        rows = fit_segments(blocks.item_size, rows_per_block, item_size=RACK_ROW_DEPTH_M, gap_size=secondary_w)
        for ri, row_start in enumerate(rows.item_starts):
            for si, seg_start in enumerate(depth_segments.item_starts):
                r = make_rect(block_start + row_start, seg_start, rows.item_size, depth_segments.item_size)
                if r.w <= 0 or r.h <= 0:
                    continue
                obj = GeoObject(
                    id=f"rack_{id_prefix}_b{bi}_r{ri}_s{si}",
                    kind="rack",
                    polygon=r.to_polygon(),
                    metadata={
                        "block": bi,
                        "row": ri,
                        "segment": si,
                        "rack_type": storage_cfg.rack_type.value,
                        "rack_orientation": storage_cfg.rack_orientation.value,
                    },
                )
                racks.append(obj)
        for gi, (gap_start, gap_size) in enumerate(rows.gaps()):
            for si, seg_start in enumerate(depth_segments.item_starts):
                r = make_rect(block_start + gap_start, seg_start, gap_size, depth_segments.item_size)
                if r.w <= 0 or r.h <= 0:
                    continue
                secondary_aisles.append(
                    GeoObject(
                        id=f"aisle_sec_{id_prefix}_b{bi}_g{gi}_s{si}",
                        kind="aisle",
                        polygon=r.to_polygon(),
                        metadata={
                            "archetype_role": ArchetypeRole.SECONDARY.value,
                            "width_class": aisles_cfg.secondary_width_class.value,
                            "width_m": secondary_w,
                            "one_way": False,
                        },
                    )
                )

    main_aisles: list[GeoObject] = []
    for gi, (gap_start, gap_size) in enumerate(blocks.gaps()):
        r = make_rect(gap_start, 0.0, gap_size, depth_axis_len)
        main_aisles.append(
            GeoObject(
                id=f"aisle_main_{id_prefix}_{gi}",
                kind="aisle",
                polygon=r.to_polygon(),
                metadata={
                    "archetype_role": ArchetypeRole.MAIN.value,
                    "width_class": aisles_cfg.main_width_class.value,
                    "width_m": main_w,
                    "one_way": False,
                },
            )
        )

    cross_aisles: list[GeoObject] = []
    for gi, (gap_start, gap_size) in enumerate(depth_segments.gaps()):
        r = make_rect(0.0, gap_start, block_axis_len, gap_size)
        cross_aisles.append(
            GeoObject(
                id=f"aisle_cross_{id_prefix}_{gi}",
                kind="aisle",
                polygon=r.to_polygon(),
                metadata={
                    "archetype_role": ArchetypeRole.CROSS.value,
                    "width_class": aisles_cfg.secondary_width_class.value,
                    "width_m": cross_w,
                    "one_way": False,
                },
            )
        )

    front_spine = make_rect(0.0, 0.0, block_axis_len, front_spine_w)
    back_spine = make_rect(0.0, depth_axis_len - back_spine_w, block_axis_len, back_spine_w)
    for spine_id, spine_rect, spine_w in (
        (f"aisle_spine_{id_prefix}_front", front_spine, front_spine_w),
        (f"aisle_spine_{id_prefix}_back", back_spine, back_spine_w),
    ):
        cross_aisles.append(
            GeoObject(
                id=spine_id,
                kind="aisle",
                polygon=spine_rect.to_polygon(),
                metadata={
                    "archetype_role": ArchetypeRole.MAIN.value,
                    "width_class": aisles_cfg.main_width_class.value,
                    "width_m": spine_w,
                    "one_way": False,
                    "spine": True,
                },
            )
        )

    return FieldResult(
        racks=racks,
        main_aisles=main_aisles,
        secondary_aisles=secondary_aisles,
        cross_aisles=cross_aisles,
        main_width_m=main_w,
        secondary_width_m=secondary_w,
    )
