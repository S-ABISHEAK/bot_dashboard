"""Generate a batch of layouts and print a diversity report.

Run from the package root:
    .venv/bin/python examples/generate_batch.py
"""
from __future__ import annotations

import json
from pathlib import Path

from fleetnet_layout.diversity.reports import build_batch_report
from fleetnet_layout.generation.generator import GeneratedLayout, LayoutGenerationError, generate_layout
from fleetnet_layout.serialization.json_io import to_json_dict, write_json

if __name__ == "__main__":
    out_dir = Path("outputs/layouts")
    out_dir.mkdir(parents=True, exist_ok=True)

    successes: list[GeneratedLayout] = []
    rejections: list[str] = []
    for seed in range(100):
        try:
            layout = generate_layout(seed)
            successes.append(layout)
            data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
            write_json(str(out_dir / f"{data['layout_id']}.json"), data)
        except LayoutGenerationError as e:
            rejections.append(e.reason)

    report = build_batch_report(successes, rejections)
    Path("outputs/reports").mkdir(parents=True, exist_ok=True)
    report.write("outputs/reports/batch_report.json")
    print(json.dumps(report.to_dict(), indent=2))
