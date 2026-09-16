"""L-flow archetype (Section B): receiving and shipping on opposite
walls (inbound band on the dock wall, outbound band on the far wall,
same split `grid.py`/`u_flow.py` use), with each band corner-biased
internally (receiving anchored toward one end of its band, shipping
toward the other) so the layout stays structurally distinct from
`grid`'s area-proportional zone ordering.

KNOWN LIMITATION (v1): true perpendicular-wall (corner) placement needs
the zone/dock band packer to support east/west walls simultaneously
with north/south (see ``generation.sampling``'s dock_wall comment and
``docks.py``'s module docstring) — building that properly means making
the packers axis-aware, deferred past this revision. What's implemented
here is the same opposite-wall split every other archetype uses, which
already satisfies the hard requirement (receiving and shipping must
never share a wall) and keeps the aisle/rack field sandwiched between
them so robots route through it rather than around it.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.archetypes.base import (
    INBOUND_ZONES as _INBOUND,
)
from fleetnet_layout.generation.archetypes.base import (
    OUTBOUND_ZONES as _OUTBOUND,
)
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

# Corner-bias within each band: receiving/returns/staging/picking lead
# the inbound band (receiving closest to one end), shipping/packing/
# returns/charging/office trail the outbound band in reverse (shipping
# closest to the *other* end) -- an "honest approximation" of L-flow's
# corner-zone signature without needing a second dock wall.
_INBOUND_ORDER = ["receiving", "staging", "picking"]
_OUTBOUND_ORDER = ["packing", "charging", "office", "returns", "shipping"]


def build(rng: np.random.Generator, cfg: LayoutConfig) -> LayoutBuildResult:
    footprint = Rect(0.0, 0.0, cfg.warehouse.length_m, cfg.warehouse.width_m)
    wall = cfg.structural_constraints.dock_wall
    far_wall = opposite_wall(wall)

    zones = cfg.zones
    inbound_area = sum(getattr(zones, n).area_m2 for n in _INBOUND if getattr(zones, n).enabled)
    outbound_area = sum(getattr(zones, n).area_m2 for n in _OUTBOUND if getattr(zones, n).enabled)

    inbound_depth = max(min(inbound_area / footprint.w, footprint.h * 0.3), 6.0)
    outbound_depth = max(min(outbound_area / footprint.w, footprint.h * 0.3), 6.0)

    inbound_band, remainder = reserve_zone_band(footprint, wall, inbound_depth)
    outbound_band, storage_rect = reserve_zone_band(remainder, far_wall, outbound_depth)

    inbound_zones = pack_zone_band(inbound_band, zones, id_prefix="in", order=_INBOUND_ORDER)
    outbound_zones = pack_zone_band(outbound_band, zones, id_prefix="out", order=_OUTBOUND_ORDER)
    zone_result_zones = inbound_zones.zones + outbound_zones.zones

    field = build_storage_field(rng, storage_rect, cfg.storage, cfg.aisles, id_prefix="f0")

    columns = generate_column_grid(
        rng, storage_rect, cfg.structural_constraints.column_grid_spacing_m, cfg.diversity_controls.irregularity_level
    )
    racks = apply_subtractive_layer(field.racks, columns)

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
        main_aisles=field.main_aisles,
        secondary_aisles=field.secondary_aisles,
        cross_aisles=field.cross_aisles,
        zones=zone_result_zones,
        docks=docks,
        columns=columns,
    )
    if field.main_aisles:
        result.fire_lane_ids = [field.main_aisles[0].id]
    finalize_one_way(rng, result, cfg)
    return result
