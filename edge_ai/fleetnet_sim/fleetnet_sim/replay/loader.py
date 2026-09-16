"""Loads everything a replay needs from stored telemetry alone — no
rerunning the simulation. Reuses ``fleetnet_layout``'s own
``layout_from_json_dict``/``draw_layout_static`` (the same reconstruction
path the layout generator's own ``render`` CLI command uses) so the
warehouse background is drawn from the exact geometry a run actually
used, not re-derived.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from fleetnet_sim.storage.models import SimulationRun, Warehouse


@dataclass
class ReplayData:
    run_id: str
    layout: object  # SimpleNamespace from fleetnet_layout.serialization.json_io.layout_from_json_dict
    ticks: list[int]
    tick_to_time: dict[int, float]
    robots_by_tick: dict[int, list[dict]] = field(default_factory=dict)
    conflict_edges_by_tick: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    detour_robots_by_tick: dict[int, list[str]] = field(default_factory=dict)


def _nearest_tick(sorted_ticks: list[int], t: int) -> int | None:
    """Buckets an event's exact tick onto the nearest *sampled* tick
    present in robot_state_ts (conflict/congestion events fire every
    tick — see ``ConflictEvent``/``CongestionEvent`` — but
    ``robot_state_ts`` is subsampled, see ``TelemetryConfig``). Bucketing
    on integer tick distance rather than float ``simulation_time``
    avoids any dt floating-point comparison fragility."""
    if not sorted_ticks:
        return None
    i = bisect_left(sorted_ticks, t)
    candidates = [j for j in (i - 1, i) if 0 <= j < len(sorted_ticks)]
    if not candidates:
        return None
    best = min(candidates, key=lambda j: abs(sorted_ticks[j] - t))
    return sorted_ticks[best]


def load_replay_data(session: Session, run_id: str) -> ReplayData:
    from fleetnet_layout.serialization.json_io import layout_from_json_dict

    run = session.get(SimulationRun, run_id)
    if run is None:
        raise ValueError(f"no such run_id: {run_id!r}")
    warehouse = session.get(Warehouse, run.layout_id)
    if warehouse is None:
        raise ValueError(f"run {run_id!r} references layout_id {run.layout_id!r}, not found in warehouses table")
    layout_json = warehouse.raw_layout_json
    if isinstance(layout_json, str):
        layout_json = json.loads(layout_json)
    layout = layout_from_json_dict(layout_json)

    conn = session.connection()
    states_q = text(
        "SELECT tick, simulation_time, robot_id, x, y, yaw, task_state, speed "
        "FROM robot_state_ts WHERE run_id = :run_id ORDER BY tick"
    )
    states = pd.read_sql(states_q, conn, params={"run_id": run_id})
    if states.empty:
        raise ValueError(f"no robot_state_ts rows for run_id {run_id!r} — was the run actually simulated (not just registered)?")

    ticks = sorted(states["tick"].unique().tolist())
    tick_to_time = states.drop_duplicates("tick").set_index("tick")["simulation_time"].to_dict()

    robots_by_tick: dict[int, list[dict]] = defaultdict(list)
    for row in states.itertuples(index=False):
        robots_by_tick[row.tick].append(
            {"robot_id": row.robot_id, "x": row.x, "y": row.y, "yaw": row.yaw, "task_state": row.task_state, "speed": row.speed}
        )

    conflict_q = text("SELECT tick, yielder_robot_id, winner_robot_id FROM conflict_events WHERE run_id = :run_id")
    conflict_rows = pd.read_sql(conflict_q, conn, params={"run_id": run_id})
    conflict_edges_by_tick: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for row in conflict_rows.itertuples(index=False):
        tk = _nearest_tick(ticks, row.tick)
        if tk is not None:
            conflict_edges_by_tick[tk].append((row.yielder_robot_id, row.winner_robot_id))

    detour_q = text("SELECT tick, robot_id FROM congestion_events WHERE run_id = :run_id")
    detour_rows = pd.read_sql(detour_q, conn, params={"run_id": run_id})
    detour_robots_by_tick: dict[int, list[str]] = defaultdict(list)
    for row in detour_rows.itertuples(index=False):
        tk = _nearest_tick(ticks, row.tick)
        if tk is not None:
            detour_robots_by_tick[tk].append(row.robot_id)

    return ReplayData(
        run_id=run_id,
        layout=layout,
        ticks=ticks,
        tick_to_time=tick_to_time,
        robots_by_tick=dict(robots_by_tick),
        conflict_edges_by_tick=dict(conflict_edges_by_tick),
        detour_robots_by_tick=dict(detour_robots_by_tick),
    )


def load_frames_since(session: Session, run_id: str, since_tick: int = 0, limit: int = 200) -> dict:
    """Incremental sibling of ``load_replay_data`` — used by the
    dashboard's polling endpoint, which is hit every ~400ms for both a
    still-running simulation ("live") and a finished one ("replay").
    Re-running ``load_replay_data`` from scratch on every poll would
    re-fetch and re-serialize the entire growing telemetry history each
    time; this only fetches ticks strictly after ``since_tick``, same
    query shape as ``load_replay_data`` scoped with ``tick > :since_tick
    LIMIT :limit``.

    Returns a plain dict (not a dataclass — this is the literal shape
    the frontend's JSON response mirrors):
    ``{"run_status": str, "final_tick": int|None, "last_tick": int,
    "frames": [{"tick", "simulation_time", "robots", "conflict_edges",
    "detour_robot_ids"}]}``.

    Never raises for "no rows yet" — a run that has started but not yet
    flushed any telemetry (or genuinely has none in this tick range)
    returns an empty ``frames`` list with ``last_tick`` unchanged, since
    the frontend's poll loop treats that as "nothing new yet," not an
    error.
    """
    run = session.get(SimulationRun, run_id)
    if run is None:
        raise ValueError(f"no such run_id: {run_id!r}")

    conn = session.connection()
    states_q = text(
        "SELECT tick, simulation_time, robot_id, x, y, yaw, task_state, speed "
        "FROM robot_state_ts WHERE run_id = :run_id AND tick > :since_tick ORDER BY tick LIMIT :limit"
    )
    # LIMIT counts rows, not ticks (each tick has one row per robot) —
    # pull comfortably more rows than `limit` ticks could ever need
    # (bounded by a generous per-tick fleet-size assumption) so a
    # partial-tick page never gets sliced mid-tick.
    states = pd.read_sql(states_q, conn, params={"run_id": run_id, "since_tick": since_tick, "limit": limit * 200})

    robots_by_tick: dict[int, list[dict]] = defaultdict(list)
    for row in states.itertuples(index=False):
        robots_by_tick[row.tick].append(
            {"robot_id": row.robot_id, "x": row.x, "y": row.y, "yaw": row.yaw, "task_state": row.task_state, "speed": row.speed}
        )
    ticks = sorted(robots_by_tick.keys())[:limit]
    tick_to_time = states.drop_duplicates("tick").set_index("tick")["simulation_time"].to_dict() if not states.empty else {}

    conflict_edges_by_tick: dict[int, list[tuple[str, str]]] = defaultdict(list)
    detour_robots_by_tick: dict[int, list[str]] = defaultdict(list)
    if ticks:
        conflict_q = text(
            "SELECT tick, yielder_robot_id, winner_robot_id FROM conflict_events "
            "WHERE run_id = :run_id AND tick >= :lo AND tick <= :hi"
        )
        conflict_rows = pd.read_sql(conflict_q, conn, params={"run_id": run_id, "lo": ticks[0], "hi": ticks[-1]})
        for row in conflict_rows.itertuples(index=False):
            tk = _nearest_tick(ticks, row.tick)
            if tk is not None:
                conflict_edges_by_tick[tk].append((row.yielder_robot_id, row.winner_robot_id))

        detour_q = text(
            "SELECT tick, robot_id FROM congestion_events WHERE run_id = :run_id AND tick >= :lo AND tick <= :hi"
        )
        detour_rows = pd.read_sql(detour_q, conn, params={"run_id": run_id, "lo": ticks[0], "hi": ticks[-1]})
        for row in detour_rows.itertuples(index=False):
            tk = _nearest_tick(ticks, row.tick)
            if tk is not None:
                detour_robots_by_tick[tk].append(row.robot_id)

    frames = [
        {
            "tick": tk,
            "simulation_time": tick_to_time.get(tk),
            "robots": robots_by_tick[tk],
            "conflict_edges": conflict_edges_by_tick.get(tk, []),
            "detour_robot_ids": detour_robots_by_tick.get(tk, []),
        }
        for tk in ticks
    ]

    return {
        "run_status": run.status,
        "final_tick": run.final_tick,
        "last_tick": ticks[-1] if ticks else since_tick,
        "frames": frames,
    }
