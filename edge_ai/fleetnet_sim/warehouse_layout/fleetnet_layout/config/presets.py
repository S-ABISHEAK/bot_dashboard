"""Stress-test scenario presets (Section AB): each returns a
``SamplingOverrides`` that biases ``generation.sampling.sample_config``
toward the named scenario, still going through the normal seeded
sampling/validation pipeline rather than hand-authoring geometry.
"""
from __future__ import annotations

from fleetnet_layout.config.enums import Archetype, DockWall, IndustryType, ScaleClass
from fleetnet_layout.generation.sampling import SamplingOverrides

PRESETS: dict[str, SamplingOverrides] = {
    "normal": SamplingOverrides(),
    "high_density": SamplingOverrides(
        scale_class=ScaleClass.MEDIUM, industry_type=IndustryType.ECOMMERCE, archetype=Archetype.ZONE_BASED
    ),
    "bottleneck_heavy": SamplingOverrides(
        archetype=Archetype.U_FLOW, dock_wall=DockWall.SOUTH, irregularity_level=0.1
    ),
    "irregular": SamplingOverrides(archetype=Archetype.GRID, irregularity_level=0.9),
    "multi_zone": SamplingOverrides(archetype=Archetype.ZONE_BASED),
    "large": SamplingOverrides(scale_class=ScaleClass.LARGE, archetype=Archetype.CENTRAL_CORRIDOR),
    "narrow_aisle": SamplingOverrides(industry_type=IndustryType.ECOMMERCE, archetype=Archetype.GRID),
    "high_intersection": SamplingOverrides(scale_class=ScaleClass.LARGE, archetype=Archetype.GRID),
}


def get_preset(name: str) -> SamplingOverrides:
    if name not in PRESETS:
        raise KeyError(f"unknown preset '{name}'; available: {sorted(PRESETS)}")
    return PRESETS[name]
