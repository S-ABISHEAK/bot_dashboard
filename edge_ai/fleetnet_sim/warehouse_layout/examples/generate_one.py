"""Generate a single layout, write its JSON, and render a PNG.

Run from the package root:
    .venv/bin/python examples/generate_one.py
"""
from __future__ import annotations

from pathlib import Path

from fleetnet_layout.config.enums import Archetype, IndustryType, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict, write_json
from fleetnet_layout.visualization.renderer import render_layout

if __name__ == "__main__":
    overrides = SamplingOverrides(
        scale_class=ScaleClass.MEDIUM,
        industry_type=IndustryType.ECOMMERCE,
        archetype=Archetype.GRID,
    )
    layout = generate_layout(seed=42, overrides=overrides)

    Path("outputs/layouts").mkdir(parents=True, exist_ok=True)
    Path("outputs/renders").mkdir(parents=True, exist_ok=True)

    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    write_json(f"outputs/layouts/{data['layout_id']}.json", data)
    render_layout(layout, f"outputs/renders/{data['layout_id']}.png")

    print(f"layout_id={data['layout_id']}")
    print(f"valid={layout.validation.valid}, attempts={layout.attempts}")
    print(f"aisles={layout.metrics.aisle_count}, intersections={layout.metrics.intersection_count}")
