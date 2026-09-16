"""GET /api/runs/{run_id}/report -- one consolidated, presentation-ready
view of a completed (or in-progress) run: the same summary
`routes_runs.get_run` returns, plus time-bucketed timelines (task
completions, conflicts, congestion detours, replans) and a downsampled
full trajectory per robot. Built for the dashboard's Report tab, which
renders this as KPI cards + charts + a static trajectory map instead of
raw JSON -- see routes_runs.py for the plain per-run detail endpoint
this one builds on.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from fleetnet_sim.dashboard.db_session import db_session
from fleetnet_sim.storage.models import RunMetrics, SimulationRun

router = APIRouter()

_BUCKET_S = 10.0
_MAX_TRAJECTORY_POINTS = 150


def _timeline(session, table: str, run_id: str, extra_where: str = "") -> list[dict]:
    """Count rows per _BUCKET_S-second bucket of simulation_time."""
    rows = session.execute(
        text(
            f"SELECT floor(simulation_time / :bucket) * :bucket AS t, COUNT(*) AS n "
            f"FROM {table} WHERE run_id = :run_id {extra_where} "
            f"GROUP BY t ORDER BY t"
        ),
        {"run_id": run_id, "bucket": _BUCKET_S},
    ).mappings().all()
    return [{"t": float(r["t"]), "count": r["n"]} for r in rows]


def _cumulative_task_completions(session, run_id: str) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT floor(simulation_time / :bucket) * :bucket AS t, COUNT(*) AS n "
            "FROM task_lifecycle_events WHERE run_id = :run_id AND event = 'task_completed' "
            "GROUP BY t ORDER BY t"
        ),
        {"run_id": run_id, "bucket": _BUCKET_S},
    ).mappings().all()
    out = []
    running_total = 0
    for r in rows:
        running_total += r["n"]
        out.append({"t": float(r["t"]), "completed": r["n"], "cumulative": running_total})
    return out


def _trajectories(session, run_id: str) -> dict:
    ticks = session.execute(
        text("SELECT MIN(tick) AS lo, MAX(tick) AS hi FROM robot_state_ts WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).mappings().one()
    if ticks["lo"] is None:
        return {}
    span_ticks = (ticks["hi"] - ticks["lo"]) or 1
    robot_ids = [
        r[0]
        for r in session.execute(
            text("SELECT DISTINCT robot_id FROM robot_state_ts WHERE run_id = :run_id ORDER BY robot_id"),
            {"run_id": run_id},
        ).all()
    ]
    stride = max(1, span_ticks // _MAX_TRAJECTORY_POINTS)
    trajectories: dict[str, list[list[float]]] = {}
    for rid in robot_ids:
        rows = session.execute(
            text(
                "SELECT x, y FROM robot_state_ts "
                "WHERE run_id = :run_id AND robot_id = :rid AND (tick - :lo) % :stride = 0 "
                "ORDER BY tick"
            ),
            {"run_id": run_id, "rid": rid, "lo": ticks["lo"], "stride": stride},
        ).all()
        trajectories[rid] = [[round(x, 2), round(y, 2)] for x, y in rows]
    return trajectories


@router.get("/runs/{run_id}/report")
def get_run_report(run_id: str, request: Request):
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
            "task_timeline": _cumulative_task_completions(session, run_id),
            "conflict_timeline": _timeline(session, "conflict_events", run_id),
            "congestion_timeline": _timeline(session, "congestion_events", run_id),
            "replan_timeline": _timeline(session, "route_events", run_id),
            "trajectories": _trajectories(session, run_id),
        }
