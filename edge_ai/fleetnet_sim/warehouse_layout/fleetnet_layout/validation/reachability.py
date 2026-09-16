"""Per-zone aisle-access check (Section L rule 6, narrower form).

Complements ``validation.connectivity.check_zone_reachability`` (which
only checks graph degree): this additionally confirms the zone's own
polygon geometrically touches at least one aisle, catching a zone that
got a graph edge to some *other* far-away node through a bug, without
actually being physically adjacent to any aisle.
"""
from __future__ import annotations

from fleetnet_layout.generation.types import LayoutBuildResult


def check_zone_has_aisle_access(result: LayoutBuildResult) -> list[str]:
    failures = []
    aisle_polys = [a.polygon for a in result.all_aisles]
    for zone in result.zones:
        if not any(zone.polygon.intersects(p) for p in aisle_polys):
            failures.append(f"zone_no_aisle_access:{zone.metadata.get('zone_type', zone.id)}")
    return failures
