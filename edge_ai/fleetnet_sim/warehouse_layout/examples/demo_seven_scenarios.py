"""Required demonstration (Section AN): generate + render the seven named
scenarios, and report per-scenario metrics.

Run from the package root:
    .venv/bin/python examples/demo_seven_scenarios.py
"""
from __future__ import annotations

from pathlib import Path

from fleetnet_layout.config.enums import Archetype, IndustryType, ScaleClass
from fleetnet_layout.generation.generator import LayoutGenerationError, generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict, write_json
from fleetnet_layout.visualization.renderer import render_layout

SCENARIOS = {
    "1_small_u_flow": (1, SamplingOverrides(scale_class=ScaleClass.SMALL, archetype=Archetype.U_FLOW)),
    "2_medium_grid": (2, SamplingOverrides(scale_class=ScaleClass.MEDIUM, archetype=Archetype.GRID)),
    "3_large_central_corridor": (3, SamplingOverrides(scale_class=ScaleClass.LARGE, archetype=Archetype.CENTRAL_CORRIDOR)),
    "4_high_density_ecommerce": (
        4,
        SamplingOverrides(scale_class=ScaleClass.MEDIUM, industry_type=IndustryType.ECOMMERCE, archetype=Archetype.ZONE_BASED),
    ),
    "5_bottleneck_heavy": (5, SamplingOverrides(archetype=Archetype.U_FLOW, irregularity_level=0.1)),
    "6_irregular": (6, SamplingOverrides(scale_class=ScaleClass.MEDIUM, archetype=Archetype.GRID, irregularity_level=0.9)),
    "7_multi_zone": (7, SamplingOverrides(scale_class=ScaleClass.MEDIUM, archetype=Archetype.ZONE_BASED)),
}

if __name__ == "__main__":
    out_dir = Path("outputs/renders")
    layout_dir = Path("outputs/layouts")
    out_dir.mkdir(parents=True, exist_ok=True)
    layout_dir.mkdir(parents=True, exist_ok=True)

    for name, (seed, overrides) in SCENARIOS.items():
        try:
            layout = generate_layout(seed, overrides)
        except LayoutGenerationError as e:
            print(f"{name}: FAILED - {e.reason}")
            continue

        data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
        write_json(str(layout_dir / f"{name}.json"), data)
        render_layout(layout, str(out_dir / f"{name}.png"), title=name)

        m = layout.metrics
        print(
            f"{name}: valid={layout.validation.valid} attempts={layout.attempts} "
            f"archetype={layout.config.warehouse.archetype.value} scale={layout.config.warehouse.scale_class.value} "
            f"area={layout.config.warehouse.area_m2:.0f}m2 aisles={m.aisle_count} "
            f"intersections={m.intersection_count} dead_ends={m.dead_end_count} "
            f"density={m.storage_density:.2f} bottlenecks={len(m.bottleneck_candidates)}"
        )
