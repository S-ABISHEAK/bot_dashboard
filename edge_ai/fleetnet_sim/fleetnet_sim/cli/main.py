"""``python -m fleetnet_sim`` entry point.

Subcommands (Section 24, thin-slice subset): ``simulate``, ``batch``,
``inspect-run``, ``metrics``, ``export-dataset``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from fleetnet_sim.config.schema import (
    AlgorithmsConfig,
    DatabaseConfig,
    ExperimentConfig,
    FleetConfig,
    SimulationConfig,
    TaskGenConfig,
    WarehouseConfig,
)
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.integration.world_bridge import build_world_bridge
from fleetnet_sim.metrics.run_metrics import compute_run_metrics
from fleetnet_sim.scenarios.presets import PRESETS, get_preset
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector


def _load_layout(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _resolve_scenario(args):
    """Starts from ``--preset``'s bundle (or hardcoded defaults if no
    preset given), then lets any *explicitly passed* --robots/--dt/
    --duration/--arrival-rate flag override just that one field — so
    ``--preset dense --robots 30`` means "the dense preset, but with 30
    robots instead of its default 25." Returns (fleet, tasks, algorithms,
    dt, duration_s)."""
    if args.preset:
        preset = get_preset(args.preset)
        fleet, tasks, algorithms = preset.fleet, preset.tasks, preset.algorithms
        dt, duration = preset.dt, preset.duration_s
    else:
        fleet, tasks, algorithms = FleetConfig(), TaskGenConfig(), AlgorithmsConfig()
        dt, duration = 0.1, 300.0

    if getattr(args, "robots", None) is not None:
        fleet = fleet.model_copy(update={"robot_count": args.robots})
    if getattr(args, "arrival_rate", None) is not None:
        tasks = tasks.model_copy(update={"arrival_rate_per_s": args.arrival_rate})
    if getattr(args, "dt", None) is not None:
        dt = args.dt
    if getattr(args, "duration", None) is not None:
        duration = args.duration
    return fleet, tasks, algorithms, dt, duration


def _build_config(args) -> ExperimentConfig:
    fleet, tasks, algorithms, dt, duration = _resolve_scenario(args)
    return ExperimentConfig(
        experiment_id=args.experiment_id or f"exp_{uuid.uuid4().hex[:8]}",
        run_id=args.run_id or f"run_{uuid.uuid4().hex[:8]}",
        warehouse=WarehouseConfig(layout_path=args.layout),
        simulation=SimulationConfig(dt=dt, duration_s=duration, seed=args.seed),
        fleet=fleet,
        tasks=tasks,
        algorithms=algorithms,
    )


def _run_simulation(config: ExperimentConfig, *, skip_schema_init: bool = False) -> dict:
    """Runs one simulation end to end (layout load → engine → telemetry →
    metrics → mark completed) and returns a JSON-able summary dict.
    Shared by ``simulate`` (one call) and ``batch`` (many calls against
    the same DSN, hence ``skip_schema_init`` to avoid redundant
    ``CREATE TABLE``/``create_hypertable`` calls per run).

    Never raises: any failure (bad layout path, a rare engine edge case,
    a DB error) is caught and returned as ``status="failed"`` so one bad
    combination in a ``batch`` run doesn't abort every run after it."""
    base_summary = {
        "run_id": config.run_id,
        "experiment_id": config.experiment_id,
        "layout_path": config.warehouse.layout_path,
        "robots": config.fleet.robot_count,
        "seed": config.simulation.seed,
    }
    session = None
    try:
        layout = _load_layout(config.warehouse.layout_path)
        if config.warehouse.validate_on_load and not layout.get("validation", {}).get("valid", False):
            print(f"warning: layout JSON {config.warehouse.layout_path!r} is marked invalid; simulating anyway", file=sys.stderr)

        bridge = build_world_bridge(layout)

        if not skip_schema_init:
            init_schema(config.database.dsn, config.database.echo)
        session_factory = make_session_factory(config.database.dsn, config.database.echo)
        session = session_factory()

        session.merge(
            Experiment(
                experiment_id=config.experiment_id,
                schema_version="1.0",
                sim_version="0.1.0",
            )
        )
        session.merge(
            Warehouse(
                layout_id=layout["layout_id"],
                source_path=config.warehouse.layout_path,
                archetype=layout["warehouse"]["archetype"],
                scale_class=layout["warehouse"]["scale_class"],
                industry_type=layout["warehouse"]["industry_type"],
                area_m2=layout["warehouse"]["area_m2"],
                aspect_ratio=layout["warehouse"]["aspect_ratio"],
                raw_layout_json=layout,
            )
        )
        session.merge(
            SimulationRun(
                run_id=config.run_id,
                experiment_id=config.experiment_id,
                layout_id=layout["layout_id"],
                layout_path=config.warehouse.layout_path,
                seed=config.simulation.seed,
                dt=config.simulation.dt,
                config_json=json.loads(config.model_dump_json()),
                status="running",
            )
        )
        session.commit()

        repo = BufferedRepository(session, batch_size=config.telemetry.flush_batch_size)
        collector = TelemetryCollector(repo=repo, run_id=config.run_id)

        engine = Engine(
            config=config,
            bridge=bridge,
            on_algorithm_event=collector.on_algorithm_event,
            on_task_event=collector.on_task_event,
            on_robot_sample=collector.on_robot_sample,
            on_comm_event=collector.on_comm_event,
            on_edge_sample=collector.on_edge_sample,
            on_node_sample=collector.on_node_sample,
            on_zone_sample=collector.on_zone_sample,
        )

        t0 = time.time()
        engine.run()
        wall_s = time.time() - t0

        collector.finalize(engine)

        run_metrics = compute_run_metrics(engine)
        from fleetnet_sim.storage.models import RunMetrics

        session.merge(RunMetrics(run_id=config.run_id, metrics_json=run_metrics))
        run_row = session.get(SimulationRun, config.run_id)
        run_row.status = "completed"
        run_row.final_tick = engine.clock.tick
        session.commit()

        return {
            **base_summary,
            "status": "completed",
            "ticks": engine.clock.tick,
            "sim_time_s": engine.clock.simulation_time,
            "wall_s": wall_s,
            "metrics": run_metrics,
        }
    except Exception as exc:
        if session is not None:
            session.rollback()
            run_row = session.get(SimulationRun, config.run_id)
            if run_row is not None:
                run_row.status = "failed"
                session.commit()
        return {**base_summary, "status": "failed", "error": str(exc)}


def cmd_simulate(args) -> None:
    config = _build_config(args)
    result = _run_simulation(config)
    print(f"run_id={result['run_id']} experiment_id={result['experiment_id']}")
    if result["status"] == "failed":
        print(f"FAILED: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"ticks={result['ticks']} sim_time={result['sim_time_s']:.1f}s wall={result['wall_s']:.2f}s")
    print(json.dumps(result["metrics"], indent=2))


def cmd_replay(args) -> None:
    from fleetnet_sim.replay.loader import load_replay_data
    from fleetnet_sim.replay.renderer import render_replay

    session_factory = make_session_factory(args.dsn)
    session = session_factory()
    data = load_replay_data(session, args.run_id)

    out_path = Path(args.output or f"outputs/replays/{args.run_id}.gif")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = render_replay(
        data,
        str(out_path),
        fps=args.fps,
        trail_length=args.trail,
        start_time=args.start_time,
        end_time=args.end_time,
        show_graph=args.show_graph,
    )
    print(f"wrote {n_frames} frames to {out_path}")


def cmd_dashboard(args) -> None:
    from fleetnet_sim.dashboard.server import run_server

    run_server(host=args.host, port=args.port, dsn=args.dsn, layouts_dirs=args.layouts_dir, open_browser=not args.no_browser)


def cmd_train_model(args) -> None:
    from fleetnet_sim.models.common import resolve_dataset_path

    session_factory = make_session_factory(args.dsn)
    session = session_factory()
    dataset_path, dataset_id = resolve_dataset_path(session, dataset_id=args.dataset_id, dataset_path=args.dataset_path)

    if args.model == "eta":
        from fleetnet_sim.models.eta_model import train_eta_model

        result = train_eta_model(session, dataset_path, args.output, dataset_id=dataset_id)
    elif args.model == "conflict":
        from fleetnet_sim.models.conflict_model import train_conflict_model

        result = train_conflict_model(session, dataset_path, args.output, dataset_id=dataset_id)
    elif args.model == "congestion":
        from fleetnet_sim.models.congestion_model import train_congestion_model

        result = train_congestion_model(session, dataset_path, args.output, dataset_id=dataset_id)
    else:
        print(f"unknown model {args.model}", file=sys.stderr)
        sys.exit(1)

    print(f"model_id={result.model_id} algorithm={result.algorithm} model_path={result.model_path}")
    print(json.dumps(result.metrics, indent=2))


def cmd_predict(args) -> None:
    from fleetnet_sim.models.inference import load_model_bundle, predict_snapshot

    session_factory = make_session_factory(args.dsn)
    session = session_factory()
    try:
        bundle = load_model_bundle(session, model_id=args.model_id, model_path=args.model_path, model_name=args.model_name)
        df = predict_snapshot(session, bundle, args.run_id, at_tick=args.at_tick, pair_radius_m=args.pair_radius)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"model={bundle.model_name} ({bundle.algorithm}, model_id={bundle.model_id}) run_id={args.run_id} rows={len(df)}")
    print(df.head(args.head).to_string(index=False))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"wrote {len(df)} predictions to {out_path}")


def _parse_int_list(spec: str) -> list[int]:
    """Parses '10,15,20' or '0-4' or a mix like '0-2,5,7-8' into a sorted,
    de-duplicated list of ints."""
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:  # allow a leading '-' to not be mistaken for a range
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        else:
            values.add(int(part))
    return sorted(values)


def _resolve_layouts(spec: str) -> list[str]:
    """A directory -> every *.json inside it; otherwise a comma-separated
    list of explicit paths."""
    p = Path(spec)
    if p.is_dir():
        paths = sorted(str(f) for f in p.glob("*.json"))
        if not paths:
            print(f"no .json layouts found in directory {spec!r}", file=sys.stderr)
            sys.exit(1)
        return paths
    return [s.strip() for s in spec.split(",") if s.strip()]


def _resolve_batch_scenario(args):
    """Like ``_resolve_scenario``, but for ``batch`` where ``--robots`` is
    itself the swept sweep-axis (a comma/range list, applied per-combo
    below) rather than a single override — so the preset's own fleet
    size is intentionally never used here, only its other fields
    (robot_radius_m, max_speed_mps, ...), plus tasks/algorithms/dt/
    duration. Returns (fleet_template, tasks, algorithms, dt, duration_s)."""
    if args.preset:
        preset = get_preset(args.preset)
        fleet, tasks, algorithms = preset.fleet, preset.tasks, preset.algorithms
        dt, duration = preset.dt, preset.duration_s
    else:
        fleet, tasks, algorithms = FleetConfig(), TaskGenConfig(), AlgorithmsConfig()
        dt, duration = 0.1, 300.0

    if args.arrival_rate is not None:
        tasks = tasks.model_copy(update={"arrival_rate_per_s": args.arrival_rate})
    if args.dt is not None:
        dt = args.dt
    if args.duration is not None:
        duration = args.duration
    return fleet, tasks, algorithms, dt, duration


def cmd_batch(args) -> None:
    layouts = _resolve_layouts(args.layouts)
    seeds = _parse_int_list(args.seeds)
    robot_counts = _parse_int_list(args.robots)
    experiment_id = args.experiment_id or f"batch_{uuid.uuid4().hex[:8]}"
    dsn = args.dsn
    fleet_template, tasks, algorithms, dt, duration = _resolve_batch_scenario(args)

    combos = [(layout, seed, robots) for layout in layouts for seed in seeds for robots in robot_counts]
    print(f"experiment_id={experiment_id} — {len(combos)} runs ({len(layouts)} layouts x {len(seeds)} seeds x {len(robot_counts)} robot counts)")

    # One create_all/create_hypertable pass up front, not once per run.
    init_schema(dsn)

    results = []
    for i, (layout_path, seed, robots) in enumerate(combos, start=1):
        run_id = f"{experiment_id}_r{i:04d}"
        config = ExperimentConfig(
            experiment_id=experiment_id,
            run_id=run_id,
            warehouse=WarehouseConfig(layout_path=layout_path),
            simulation=SimulationConfig(dt=dt, duration_s=duration, seed=seed),
            fleet=fleet_template.model_copy(update={"robot_count": robots}),
            tasks=tasks,
            algorithms=algorithms,
            database=DatabaseConfig(dsn=dsn),
        )
        t0 = time.time()
        result = _run_simulation(config, skip_schema_init=True)
        elapsed = time.time() - t0
        status = result["status"]
        print(f"[{i}/{len(combos)}] {run_id} layout={Path(layout_path).name} seed={seed} robots={robots} -> {status} ({elapsed:.1f}s)")
        if status == "failed":
            print(f"    error: {result['error']}", file=sys.stderr)
        results.append(result)

    n_ok = sum(1 for r in results if r["status"] == "completed")
    n_failed = len(results) - n_ok
    print(f"batch done: {n_ok} completed, {n_failed} failed")

    summary_path = Path(args.summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({"experiment_id": experiment_id, "runs": results}, indent=2))
    print(f"summary written to {summary_path}")

    run_ids = [r["run_id"] for r in results if r["status"] == "completed"]
    if args.export_datasets and run_ids:
        session_factory = make_session_factory(dsn)
        for model in [m.strip() for m in args.export_datasets.split(",") if m.strip()]:
            session = session_factory()
            try:
                if model == "eta":
                    from fleetnet_sim.datasets.eta_builder import build_eta_dataset

                    ds_result = build_eta_dataset(session, run_ids, args.dataset_output)
                elif model == "conflict":
                    from fleetnet_sim.datasets.conflict_builder import build_conflict_dataset

                    ds_result = build_conflict_dataset(session, run_ids, args.dataset_output, horizon_s=args.horizon)
                elif model == "congestion":
                    from fleetnet_sim.datasets.congestion_builder import build_congestion_dataset

                    ds_result = build_congestion_dataset(
                        session, run_ids, args.dataset_output, horizon_s=args.horizon, congestion_occupancy_threshold=args.congestion_threshold
                    )
                else:
                    print(f"unknown model {model!r}, skipping", file=sys.stderr)
                    continue
            except ValueError as exc:
                print(f"skipping {model} dataset export: {exc}", file=sys.stderr)
                continue
            print(f"dataset[{model}]: dataset_id={ds_result.dataset_id} rows={ds_result.n_rows} output={ds_result.output_path}")


def cmd_inspect_run(args) -> None:
    from fleetnet_sim.config.schema import DatabaseConfig

    session_factory = make_session_factory(args.dsn)
    session = session_factory()
    run = session.get(SimulationRun, args.run_id)
    if run is None:
        print(f"no such run: {args.run_id}", file=sys.stderr)
        sys.exit(1)
    print(f"run_id={run.run_id} status={run.status} seed={run.seed} layout={run.layout_id} final_tick={run.final_tick}")
    from fleetnet_sim.storage.models import RunMetrics

    rm = session.get(RunMetrics, args.run_id)
    if rm:
        print(json.dumps(rm.metrics_json, indent=2))


def cmd_export_dataset(args) -> None:
    session_factory = make_session_factory(args.dsn)
    session = session_factory()
    run_ids = args.run_ids.split(",")

    if args.model == "eta":
        from fleetnet_sim.datasets.eta_builder import build_eta_dataset

        result = build_eta_dataset(session, run_ids, args.output)
    elif args.model == "conflict":
        from fleetnet_sim.datasets.conflict_builder import build_conflict_dataset

        result = build_conflict_dataset(session, run_ids, args.output, horizon_s=args.horizon)
    elif args.model == "congestion":
        from fleetnet_sim.datasets.congestion_builder import build_congestion_dataset

        result = build_congestion_dataset(session, run_ids, args.output, horizon_s=args.horizon, congestion_occupancy_threshold=args.congestion_threshold)
    else:
        print(f"unknown model {args.model}", file=sys.stderr)
        sys.exit(1)

    print(f"dataset_id={result.dataset_id} rows={result.n_rows} output={result.output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleetnet_sim")
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="Run one simulation")
    sim.add_argument("--layout", required=True, help="Path to a warehouse_layout-generated JSON file")
    sim.add_argument("--preset", default=None, choices=sorted(PRESETS), help="Named fleet+task scenario (see scenarios/presets.py); explicit flags below override individual preset fields")
    sim.add_argument("--robots", type=int, default=None, help="Overrides the preset's robot_count (default without a preset: 10)")
    sim.add_argument("--seed", type=int, default=0)
    sim.add_argument("--dt", type=float, default=None, help="Overrides the preset's dt (default without a preset: 0.1)")
    sim.add_argument("--duration", type=float, default=None, help="Overrides the preset's duration_s (default without a preset: 300.0)")
    sim.add_argument("--arrival-rate", type=float, default=None, help="Overrides the preset's arrival_rate_per_s (default without a preset: 0.5)")
    sim.add_argument("--experiment-id", default=None)
    sim.add_argument("--run-id", default=None)
    sim.set_defaults(func=cmd_simulate)

    batch = sub.add_parser("batch", help="Run many simulate invocations (layouts x seeds x robot counts) in one command")
    batch.add_argument("--layouts", required=True, help="Comma-separated layout JSON paths, or a directory containing them")
    batch.add_argument("--seeds", required=True, help="Comma-separated ints and/or ranges, e.g. '0-9' or '1,2,5,10-12'")
    batch.add_argument("--robots", required=True, help="Comma-separated robot counts and/or ranges, e.g. '10,15,20' — always the sweep axis, even with --preset")
    batch.add_argument("--preset", default=None, choices=sorted(PRESETS), help="Named scenario for tasks/algorithms/dt/duration (robot_count is always --robots above, never the preset's)")
    batch.add_argument("--dt", type=float, default=None, help="Overrides the preset's dt (default without a preset: 0.1)")
    batch.add_argument("--duration", type=float, default=None, help="Overrides the preset's duration_s (default without a preset: 300.0)")
    batch.add_argument("--arrival-rate", type=float, default=None, help="Overrides the preset's arrival_rate_per_s (default without a preset: 0.5)")
    batch.add_argument("--experiment-id", default=None, help="Shared experiment_id for the whole batch (default: auto-generated)")
    batch.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    batch.add_argument("--summary-output", default="outputs/batch_runs/summary.json")
    batch.add_argument("--export-datasets", default=None, help="Comma-separated subset of eta,conflict,congestion to auto-build from every completed run once the batch finishes")
    batch.add_argument("--dataset-output", default="outputs/datasets")
    batch.add_argument("--horizon", type=float, default=2.0, help="Conflict/congestion models: seconds")
    batch.add_argument("--congestion-threshold", type=int, default=2, help="Congestion model only: occupancy_count considered congested")
    batch.set_defaults(func=cmd_batch)

    inspect = sub.add_parser("inspect-run", help="Print a stored run's summary/metrics")
    inspect.add_argument("--run-id", required=True)
    inspect.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    inspect.set_defaults(func=cmd_inspect_run)

    export = sub.add_parser("export-dataset", help="Build one of the three ML datasets from stored telemetry")
    export.add_argument("--model", required=True, choices=["eta", "conflict", "congestion"])
    export.add_argument("--run-ids", required=True, help="Comma-separated run_ids to include")
    export.add_argument("--output", default="outputs/datasets")
    export.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    export.add_argument("--horizon", type=float, default=2.0, help="Conflict/congestion models: seconds")
    export.add_argument("--congestion-threshold", type=int, default=2, help="Congestion model only: occupancy_count considered congested")
    export.set_defaults(func=cmd_export_dataset)

    replay = sub.add_parser("replay", help="Render a stored run's telemetry as an animated GIF (robot trails, conflicts, congestion detours)")
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--output", default=None, help="Default: outputs/replays/<run_id>.gif")
    replay.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    replay.add_argument("--fps", type=int, default=10)
    replay.add_argument("--trail", type=int, default=15, help="Number of past positions kept in each robot's fading trail")
    replay.add_argument("--start-time", type=float, default=None, help="Seconds into the run to start rendering from")
    replay.add_argument("--end-time", type=float, default=None, help="Seconds into the run to stop rendering at")
    replay.add_argument("--show-graph", action="store_true", help="Overlay the navigation graph (nodes/edges) as in warehouse_layout's own renderer")
    replay.set_defaults(func=cmd_replay)

    train = sub.add_parser("train-model", help="Train a baseline model on an exported dataset")
    train.add_argument("--model", required=True, choices=["eta", "conflict", "congestion"])
    train_source = train.add_mutually_exclusive_group(required=True)
    train_source.add_argument("--dataset-id", default=None, help="Looked up in model_dataset_registry")
    train_source.add_argument("--dataset-path", default=None, help="Direct path to a dataset .parquet file")
    train.add_argument("--output", default="outputs/models")
    train.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    train.set_defaults(func=cmd_train_model)

    predict = sub.add_parser("predict", help="Score a trained model against one tick of a stored run's telemetry")
    predict_source = predict.add_mutually_exclusive_group(required=True)
    predict_source.add_argument("--model-id", default=None, help="Looked up in trained_model_registry (preferred — traceable)")
    predict_source.add_argument("--model-path", default=None, help="Direct path to a .joblib file")
    predict.add_argument("--model-name", default=None, choices=["eta", "conflict", "congestion"], help="Required alongside --model-path (not recoverable from a bare .joblib file)")
    predict.add_argument("--run-id", required=True)
    predict.add_argument("--at-tick", type=int, default=None, help="Tick to score (default: the run's latest tick with relevant data)")
    predict.add_argument("--pair-radius", type=float, default=8.0, help="Conflict model only: meters")
    predict.add_argument("--head", type=int, default=10, help="Rows to print to stdout")
    predict.add_argument("--output", default=None, help="Optional: write full predictions to this CSV path")
    predict.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    predict.set_defaults(func=cmd_predict)

    dash = sub.add_parser("dashboard", help="Start the local web dashboard (browse layouts, launch and watch simulations)")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--dsn", default="postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim")
    dash.add_argument("--layouts-dir", action="append", default=None, help="Directory to scan for layout JSON files; repeatable. Default: warehouse_layout/outputs/layouts and .../layouts_batch")
    dash.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    dash.set_defaults(func=cmd_dashboard)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
