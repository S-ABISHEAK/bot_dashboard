"""Operational-zone placement (Section E/P).

Zones are packed into a rectangular "zone band" along the wall(s) they
belong to (receiving/shipping/staging near the dock wall; picking/
packing/charging/returns/office filling out the rest of the band, order
is a plausible flow approximation, not a hard rule). Each archetype
decides *which wall(s)* the band(s) sit against and passes the resulting
rect(s) in here; this module only does the packing arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass

from fleetnet_layout.config.schema import ZonesConfig
from fleetnet_layout.geometry.primitives import GeoObject, Rect

_ZONE_ORDER = ["receiving", "staging", "picking", "packing", "returns", "charging", "office", "shipping"]


@dataclass
class ZoneBandResult:
    zones: list[GeoObject]
    used_depth_m: float


def pack_zone_band(rect: Rect, zones_cfg: ZonesConfig, id_prefix: str, order: list[str] | None = None) -> ZoneBandResult:
    """Pack enabled zones left-to-right, filling ``rect`` exactly (depth =
    rect.h always). Using the caller-supplied rect's full depth — rather
    than recomputing an "ideal" depth from total target area — is
    deliberate: the caller (an archetype builder) already reserved
    exactly this much space via ``archetypes.base.reserve_zone_band``,
    and the adjacent storage field is built to start precisely at
    ``rect.y + rect.h``. A band that only partially fills its reserved
    depth leaves a sliver of unowned space between the zones and the
    storage field's connecting spine aisle, silently disconnecting every
    zone in the band from the navigation graph (see graph/builder.py's
    zone-attachment step) — this was a real bug caught by
    tests/test_graph.py's full-connectivity sweep, not a hypothetical."""
    order = order or _ZONE_ORDER
    specs = [(name, getattr(zones_cfg, name)) for name in order if getattr(zones_cfg, name).enabled]
    if not specs:
        return ZoneBandResult(zones=[], used_depth_m=0.0)

    depth = max(rect.h, 1e-3)
    widths = [spec.area_m2 / depth for _, spec in specs]
    total_width = sum(widths)
    if total_width > rect.w:
        scale = rect.w / total_width
        widths = [w * scale for w in widths]

    zones: list[GeoObject] = []
    cursor = 0.0
    for (name, spec), w in zip(specs, widths):
        r = Rect(rect.x + cursor, rect.y, w, depth)
        zones.append(
            GeoObject(
                id=f"zone_{id_prefix}_{name}",
                kind="zone",
                polygon=r.to_polygon(),
                metadata={"zone_type": name, "target_area_m2": spec.area_m2},
            )
        )
        cursor += w

    return ZoneBandResult(zones=zones, used_depth_m=depth)
