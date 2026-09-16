"""``python -m fleetnet_layout`` entry point (Section AA).

Subcommands: generate (single), batch (N with optional filters), render,
validate, report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fleetnet_layout.config.enums import Archetype, IndustryType, ScaleClass
from fleetnet_layout.config.presets import PRESETS, get_preset
from fleetnet_layout.diversity.reports import build_batch_report
from fleetnet_layout.generation.generator import GeneratedLayout, LayoutGenerationError, generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import read_json, to_json_dict, write_json
from fleetnet_layout.visualization.renderer import render_layout


def _overrides_from_args(args) -> SamplingOverrides:
    base = get_preset(args.preset) if getattr(args, "preset", None) else SamplingOverrides()
    return SamplingOverrides(
        scale_class=ScaleClass(args.scale) if getattr(args, "scale", None) else base.scale_class,
        industry_type=IndustryType(args.industry) if getattr(args, "industry", None) else base.industry_type,
        archetype=Archetype(args.archetype) if getattr(args, "archetype", None) else base.archetype,
        irregularity_level=getattr(args, "irregularity", None) if getattr(args, "irregularity", None) is not None else base.irregularity_level,
        dock_wall=base.dock_wall,
    )


def cmd_generate(args) -> None:
    overrides = _overrides_from_args(args)
    try:
        layout = generate_layout(args.seed, overrides)
    except LayoutGenerationError as e:
        print(f"generation failed: {e}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    json_path = out_dir / f"{data['layout_id']}.json"
    write_json(str(json_path), data)
    print(f"wrote {json_path}")

    if args.visualize:
        render_dir = Path(args.render_output)
        render_dir.mkdir(parents=True, exist_ok=True)
        png_path = render_dir / f"{data['layout_id']}.png"
        render_layout(layout, str(png_path))
        print(f"wrote {png_path}")


def cmd_batch(args) -> None:
    overrides = _overrides_from_args(args)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    successes: list[GeneratedLayout] = []
    rejection_log: list[str] = []
    for i in range(args.count):
        seed = args.seed + i
        try:
            layout = generate_layout(seed, overrides)
            successes.append(layout)
            data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
            write_json(str(out_dir / f"{data['layout_id']}.json"), data)
        except LayoutGenerationError as e:
            rejection_log.append(e.reason)

    report = build_batch_report(successes, rejection_log)
    report_path = Path(args.report_output) / "batch_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.write(str(report_path))
    print(f"batch done: {report.valid_count} valid, {report.rejected_count} rejected")
    print(f"report written to {report_path}")


def _render_one(json_path: Path, out_path: Path) -> None:
    from fleetnet_layout.serialization.json_io import layout_from_json_dict

    data = read_json(str(json_path))
    layout = layout_from_json_dict(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render_layout(layout, str(out_path), title=data.get("layout_id"))
    print(f"wrote {out_path}")


def cmd_render(args) -> None:
    in_path = Path(args.input)
    out_dir = Path(args.output_dir)

    if in_path.is_dir():
        json_files = sorted(in_path.glob("*.json"))
        if not json_files:
            print(f"no .json files found in {in_path}", file=sys.stderr)
            sys.exit(1)
        for jf in json_files:
            _render_one(jf, out_dir / f"{jf.stem}.png")
    else:
        out_path = Path(args.output) if args.output else out_dir / f"{in_path.stem}.png"
        _render_one(in_path, out_path)


def cmd_validate(args) -> None:
    data = read_json(args.input)
    valid = data.get("validation", {}).get("valid")
    print(f"valid: {valid}")
    if not valid:
        for f in data.get("validation", {}).get("failures", []):
            print(f"  - {f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleetnet_layout")
    sub = parser.add_subparsers(dest="command", required=True)

    common = dict(
        scale=dict(choices=[s.value for s in ScaleClass]),
        industry=dict(choices=[i.value for i in IndustryType]),
        archetype=dict(choices=[a.value for a in Archetype]),
    )

    gen = sub.add_parser("generate", help="Generate a single layout")
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--preset", choices=sorted(PRESETS))
    gen.add_argument("--scale", **common["scale"])
    gen.add_argument("--industry", **common["industry"])
    gen.add_argument("--archetype", **common["archetype"])
    gen.add_argument("--irregularity", type=float, default=None)
    gen.add_argument("--output", default="outputs/layouts")
    gen.add_argument("--render-output", default="outputs/renders")
    gen.add_argument("--visualize", action="store_true")
    gen.set_defaults(func=cmd_generate)

    batch = sub.add_parser("batch", help="Generate a batch of layouts")
    batch.add_argument("--count", type=int, default=100)
    batch.add_argument("--seed", type=int, default=0)
    batch.add_argument("--preset", choices=sorted(PRESETS))
    batch.add_argument("--scale", **common["scale"])
    batch.add_argument("--industry", **common["industry"])
    batch.add_argument("--archetype", **common["archetype"])
    batch.add_argument("--irregularity", type=float, default=None)
    batch.add_argument("--output", default="outputs/layouts")
    batch.add_argument("--report-output", default="outputs/reports")
    batch.set_defaults(func=cmd_batch)

    render = sub.add_parser("render", help="Render a stored layout JSON (or a folder of them) to PNG")
    render.add_argument("--input", required=True, help="A single layout .json file, or a directory of them")
    render.add_argument("--output", default=None, help="Output PNG path (single-file input only)")
    render.add_argument("--output-dir", default="outputs/renders", help="Output directory (used for directory input, or as default for single-file)")
    render.set_defaults(func=cmd_render)

    validate = sub.add_parser("validate", help="Print the validation result of a stored layout JSON")
    validate.add_argument("--input", required=True)
    validate.set_defaults(func=cmd_validate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
