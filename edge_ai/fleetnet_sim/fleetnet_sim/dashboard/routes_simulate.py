"""POST /api/simulate, GET /api/simulate/{run_id}/status — launching and
tracking dashboard-initiated simulations.

Reuses `fleetnet_sim.cli.main._resolve_scenario` (the exact function
`simulate`/`batch` use to layer a preset with explicit overrides) so the
dashboard can never drift from CLI behavior — it's fed a small
duck-typed namespace instead of an argparse.Namespace, since
`_resolve_scenario` only ever does `args.preset`/`getattr(args, "robots",
None)`-style attribute access.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request

from fleetnet_sim.cli.main import _resolve_scenario
from fleetnet_sim.config.schema import (
    DatabaseConfig,
    ExperimentConfig,
    SimulationConfig,
    TelemetryConfig,
    WarehouseConfig,
)
from fleetnet_sim.dashboard.jobs import ConcurrencyLimitError
from fleetnet_sim.dashboard.schemas import JobStatusResponse, LaunchRequest, LaunchResponse

router = APIRouter()

# Smaller than the CLI's default (500) so telemetry lands in Postgres
# promptly enough for the dashboard's ~400ms poll loop to see it while
# the run is still in progress -- see the plan's live-playback design
# note. Pure config, zero change to BufferedRepository/TelemetryCollector.
DASHBOARD_TELEMETRY = TelemetryConfig(flush_batch_size=25, flush_interval_s=0.5)


@router.post("/simulate", response_model=LaunchResponse, status_code=202)
def launch_simulation(body: LaunchRequest, request: Request):
    if body.layout_path:
        layout_path = body.layout_path
    elif body.layout_id:
        path = request.app.state.layout_index.find_path(body.layout_id)
        if path is None:
            raise HTTPException(status_code=404, detail=f"no such layout_id: {body.layout_id!r}")
        layout_path = str(path)
    else:
        raise HTTPException(status_code=422, detail="must supply layout_id or layout_path")

    ns = SimpleNamespace(
        preset=body.preset,
        robots=body.robots,
        arrival_rate=body.arrival_rate,
        dt=body.dt,
        duration=body.duration_s,
    )
    try:
        fleet, tasks, algorithms, dt, duration = _resolve_scenario(ns)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run_id = f"dash_{uuid.uuid4().hex[:10]}"
    experiment_id = f"dash_exp_{uuid.uuid4().hex[:8]}"
    config = ExperimentConfig(
        experiment_id=experiment_id,
        run_id=run_id,
        warehouse=WarehouseConfig(layout_path=layout_path),
        simulation=SimulationConfig(dt=dt, duration_s=duration, seed=body.seed),
        fleet=fleet,
        tasks=tasks,
        algorithms=algorithms,
        telemetry=DASHBOARD_TELEMETRY,
        database=DatabaseConfig(dsn=request.app.state.dsn),
    )

    try:
        request.app.state.jobs.start(config)
    except ConcurrencyLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    return LaunchResponse(run_id=run_id, experiment_id=experiment_id, status="started")


@router.get("/simulate/{run_id}/status", response_model=JobStatusResponse)
def simulate_status(run_id: str, request: Request):
    job = request.app.state.jobs.get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no tracked job for run_id: {run_id!r}")
    return JobStatusResponse(run_id=job.run_id, status=job.status, error=job.error)
