"""GET /api/runs, GET /api/runs/{run_id}, GET /api/runs/{run_id}/frames —
run history, detail, and the core live/replay polling endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from fleetnet_sim.dashboard.db_session import db_session
from fleetnet_sim.replay.loader import load_frames_since
from fleetnet_sim.storage.models import RunMetrics, SimulationRun

router = APIRouter()


@router.get("/runs")
def list_runs(request: Request, limit: int = 50):
    with db_session(request) as session:
        rows = session.execute(
            text(
                "SELECT run_id, experiment_id, layout_id, status, seed, started_at, finished_at, final_tick "
                "FROM simulation_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        ).mappings().all()
        return {"runs": [dict(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    with db_session(request) as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no such run_id: {run_id!r}")
        rm = session.get(RunMetrics, run_id)
        return {
            "run_id": run.run_id,
            "experiment_id": run.experiment_id,
            "layout_id": run.layout_id,
            "layout_path": run.layout_path,
            "seed": run.seed,
            "dt": run.dt,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "final_tick": run.final_tick,
            "config": run.config_json,
            "metrics": rm.metrics_json if rm else None,
        }


@router.get("/runs/{run_id}/frames")
def get_frames(run_id: str, request: Request, since_tick: int = 0, limit: int = 200):
    with db_session(request) as session:
        try:
            return load_frames_since(session, run_id, since_tick=since_tick, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
