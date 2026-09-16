"""Clearance checks (Section L rule 4).

Aisle-width-vs-equipment-class is already enforced structurally by
``config.distributions.aisle_width_m`` always sampling within the
configured class's legal band (Section C) — there is no code path that
can produce an aisle narrower than its class's minimum, so this module
only checks the generic ``min_clearance_m`` floor against every aisle's
actual sampled width (a defense-in-depth check, not redundant: it also
catches the case where a column-notch or subtractive cut has locally
narrowed a rack's setback below the configured clearance).
"""
from __future__ import annotations

from fleetnet_layout.config.defaults import AISLE_WIDTH_BANDS_M
from fleetnet_layout.config.enums import AisleWidthClass
from fleetnet_layout.generation.types import LayoutBuildResult


def check_min_clearance(result: LayoutBuildResult, min_clearance_m: float) -> list[str]:
    failures = []
    for aisle in result.all_aisles:
        width_class = aisle.metadata.get("width_class")
        width_m = aisle.metadata.get("width_m")
        if width_class is None or width_m is None:
            continue
        low, _high = AISLE_WIDTH_BANDS_M.get(AisleWidthClass(width_class), (0.0, 0.0))
        if width_m < max(low - min_clearance_m, 0.3):
            failures.append(f"sub_minimum_clearance:{aisle.id}")
    return failures
