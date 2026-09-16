"""Receiving and shipping must never end up on the same wall.

u_flow and l_flow used to place both zones in the same dock-wall band
(u_flow explicitly; l_flow via same-wall corners) -- a real bug, since
fleetnet_sim's D* Lite planner plans over raw free space, so two zones
sharing a wall let a robot walk zone-to-zone along that wall without
ever entering the aisle/rack field (see archetypes/grid.py's module
docstring). Every archetype now uses the same inbound/outbound
opposite-wall band split.
"""
from __future__ import annotations

import pytest

from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides

ALL_ARCHETYPES = list(Archetype)


def _dock_wall_bounds(footprint_h: float, bounds: tuple[float, float, float, float]) -> set[str]:
    """Which dock wall (south/north) a zone's bbox is banded against.

    Only south/north matter here: ``sampling.py``'s dock_wall sampling
    is restricted to those two (see its module comment), and
    ``reserve_zone_band`` always splits bands along the y-axis. A zone's
    bbox touching x=0 or x=footprint_w is just an artifact of
    ``pack_zone_band`` packing left-to-right within its band and isn't a
    "wall" in the dock sense, so x-extent is deliberately not checked
    here -- checking it produces false positives (e.g. both receiving
    and shipping's packed zones can start at x=0 in their own bands
    while genuinely sitting on opposite y-walls).
    """
    _, miny, _, maxy = bounds
    tol = 1e-3
    walls = set()
    if abs(miny - 0.0) < tol:
        walls.add("south")
    if abs(maxy - footprint_h) < tol:
        walls.add("north")
    return walls


@pytest.mark.parametrize("archetype", ALL_ARCHETYPES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_receiving_and_shipping_never_share_a_wall(archetype, seed):
    layout = generate_layout(seed, SamplingOverrides(archetype=archetype, scale_class=ScaleClass.MEDIUM))
    fh = layout.config.warehouse.width_m

    zones_by_type = {z.metadata["zone_type"]: z for z in layout.result.zones}
    if "receiving" not in zones_by_type or "shipping" not in zones_by_type:
        pytest.skip("receiving/shipping not both enabled for this sampled config")

    receiving_walls = _dock_wall_bounds(fh, zones_by_type["receiving"].polygon.bounds)
    shipping_walls = _dock_wall_bounds(fh, zones_by_type["shipping"].polygon.bounds)

    assert receiving_walls, f"receiving zone doesn't touch any footprint wall: {zones_by_type['receiving'].polygon.bounds}"
    assert shipping_walls, f"shipping zone doesn't touch any footprint wall: {zones_by_type['shipping'].polygon.bounds}"
    assert not (receiving_walls & shipping_walls), (
        f"{archetype} seed={seed}: receiving ({receiving_walls}) and shipping ({shipping_walls}) "
        "share a wall -- robots can walk zone-to-zone without entering the aisle field"
    )
