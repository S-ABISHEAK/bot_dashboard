"""Task ETA Predictor dataset -- frozen 23-feature schema (see the
FleetNet Edge-AI spec's Task ETA Predictor section), minus 2 dropped
per an explicit decision this session: ``battery_voltage`` and
``payload_mass_kg`` have no underlying data anywhere -- the simulation
has no battery or payload model at all -- so V1 ships 21/23 features
rather than fabricate them. This is recorded in ``DROPPED_FROM_V1``
and in every exported dataset's schema.json, not silently.

One row per sampled ``robot_state_ts`` observation while a robot is
actively en route to a pickup/dropoff (``task_state`` in
``TO_PICKUP``/``TO_DROPOFF``). Label = the task's actual remaining
completion time from that observation instant -- only defined (and only
included) for tasks that eventually completed, per Section 19's "ETA
observations after task completion are excluded" (an observation is, by
construction, always strictly before completion here).

Several features are honest, clearly-labeled proxies (no persisted
edge-sequence/route exists, only ``route_events.route_hash``/
``route_length_m``) -- see ``PROXY_FEATURE_NOTES``.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.splits import split_for_run
from fleetnet_sim.datasets.warehouse_context import ROBOT_DIAMETER_M, canon_edge, get_warehouse_context
from fleetnet_sim.storage.models import ModelDatasetRegistry

FEATURE_VERSION = "eta_v2"
STOP_SPEED_MPS = 0.05

FEATURE_COLUMNS = [
    "remaining_distance_m", "planned_path_length_m", "path_turn_count", "path_curvature",
    "route_edge_count", "current_speed_mps", "max_speed_mps", "acceleration_mps2",
    "workload_count", "task_priority", "task_type_encoded", "source_zone_type",
    "destination_zone_type", "destination_queue_depth", "local_traffic_density",
    "edge_congestion_score", "waiting_time_so_far_s", "stop_count", "replan_count",
    "task_age_s", "historical_delay_factor",
]
DROPPED_FROM_V1 = ["battery_voltage", "payload_mass_kg"]
DROPPED_FROM_V1_REASON = "no battery or payload model exists anywhere in the simulation -- nothing to extract, not faked"
PROXY_FEATURE_NOTES = {
    "route_edge_count": "distinct edges (current_edge_source/target) visited so far this task, from sampled robot_state_ts -- not the full planned route (not persisted)",
    "path_turn_count": "count of yaw changes > TURN_THRESHOLD_RAD between consecutive samples so far this task",
    "path_curvature": "cumulative |yaw delta| so far this task (radians), a turn-cost proxy",
    "edge_congestion_score": "occupancy/capacity of the robot's current edge at this tick (edge_state_ts + warehouse geometry), same formula as the Congestion Predictor's edge_occupancy_ratio",
    "waiting_time_so_far_s": "accumulated seconds this robot has spent below STOP_SPEED_MPS since this task started",
    "historical_delay_factor": "this robot's own average completion time (over its completed tasks so far in the run) divided by the fleet-wide average so far; 1.0 (neutral) when there isn't enough history yet",
}
TURN_THRESHOLD_RAD = 0.35  # ~20 degrees between consecutive samples counts as a discrete "turn"


@dataclass
class ETADatasetResult:
    dataset_id: str
    output_path: str
    n_rows: int
    n_runs: int


def _local_density(df_states: pd.DataFrame, radius_m: float = 5.0) -> pd.Series:
    """Count of other robots within radius_m, at the same (run_id, tick)."""
    density = pd.Series(0, index=df_states.index)
    for (run_id, tick), group in df_states.groupby(["run_id", "tick"]):
        coords = group[["x", "y"]].to_numpy()
        n = len(coords)
        for local_i in range(n):
            dx = coords[:, 0] - coords[local_i, 0]
            dy = coords[:, 1] - coords[local_i, 1]
            d = (dx**2 + dy**2) ** 0.5
            density.loc[group.index[local_i]] = int(((d > 1e-9) & (d <= radius_m)).sum())
    return density


def _run_layout_ids(session: Session, run_ids: list[str]) -> dict[str, str]:
    q = text("SELECT run_id, layout_id FROM simulation_runs WHERE run_id IN :run_ids").bindparams(
        bindparam("run_ids", expanding=True)
    )
    return dict(session.execute(q, {"run_ids": run_ids}).all())


def _robot_max_speed(session: Session, run_ids: list[str]) -> dict[tuple[str, str], float]:
    q = text("SELECT run_id, robot_id, max_speed_mps FROM robots WHERE run_id IN :run_ids").bindparams(
        bindparam("run_ids", expanding=True)
    )
    return {(r.run_id, r.robot_id): r.max_speed_mps for r in session.execute(q, {"run_ids": run_ids}).all()}


def _edge_occupancy(session: Session, run_ids: list[str]) -> dict[tuple[str, str, int], int]:
    q = text(
        "SELECT run_id, tick, edge_source, edge_target, occupancy_count FROM edge_state_ts WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    df = pd.read_sql(q, session.connection(), params={"run_ids": run_ids})
    return {(r.run_id, canon_edge(r.edge_source, r.edge_target), r.tick): r.occupancy_count for r in df.itertuples(index=False)}


def _zone_occupancy(session: Session, run_ids: list[str]) -> dict[tuple[str, str, int], int]:
    q = text(
        "SELECT run_id, tick, zone_type, occupancy_count FROM zone_state_ts WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    df = pd.read_sql(q, session.connection(), params={"run_ids": run_ids})
    return {(r.run_id, r.zone_type, r.tick): r.occupancy_count for r in df.itertuples(index=False)}


def _all_tasks(session: Session, run_ids: list[str]) -> pd.DataFrame:
    q = text(
        "SELECT run_id, task_id, assigned_robot_id, release_time, completion_time, final_status "
        "FROM tasks WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    return pd.read_sql(q, session.connection(), params={"run_ids": run_ids})


def build_eta_dataset(session: Session, run_ids: list[str], output_dir: str) -> ETADatasetResult:
    conn = session.connection()
    states_q = text(
        "SELECT run_id, tick, simulation_time, robot_id, x, y, yaw, speed, task_id, task_state, "
        "replan_count, distance_travelled, current_edge_source, current_edge_target "
        "FROM robot_state_ts WHERE run_id IN :run_ids AND task_state IN ('TO_PICKUP', 'TO_DROPOFF') AND task_id IS NOT NULL"
    ).bindparams(bindparam("run_ids", expanding=True))
    states = pd.read_sql(states_q, conn, params={"run_ids": run_ids})
    if states.empty:
        raise ValueError("no in-progress robot_state_ts rows found for the given run_ids")

    tasks_q = text(
        "SELECT run_id, task_id, task_type, source_zone_id, destination_zone_id, priority, release_time, "
        "assignment_time, planned_distance, completion_time, final_status FROM tasks WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    tasks = pd.read_sql(tasks_q, conn, params={"run_ids": run_ids})
    completed = tasks[tasks["final_status"] == "completed"]

    df = states.merge(completed, on=["run_id", "task_id"], how="inner", suffixes=("", "_task"))

    # Label: strictly future relative to the observation (guards leakage).
    df["label_remaining_time_s"] = df["completion_time"] - df["simulation_time"]
    df = df[df["label_remaining_time_s"] > 0].copy()

    df["age_since_release_s"] = df["simulation_time"] - df["release_time"]
    df["remaining_distance_m"] = (df["planned_distance"].fillna(0) - df["distance_travelled"]).clip(lower=0)
    df["local_density"] = _local_density(df)

    layout_ids = _run_layout_ids(session, run_ids)
    robot_max_speed = _robot_max_speed(session, run_ids)
    edge_occ = _edge_occupancy(session, run_ids)
    zone_occ = _zone_occupancy(session, run_ids)
    all_tasks = _all_tasks(session, run_ids)

    # Note: `tasks.source_zone_id`/`destination_zone_id` are already the
    # zone-TYPE string (see core/task_generator.py's FLOW_EDGES -- e.g.
    # "staging", "picking") in this simulation's data model, not a
    # distinct geometry-object id -- so source/destination_zone_type is
    # just that same column, not a separate lookup.

    # Fixed, deterministic label encoding for task_type -- sorted alphabetically
    # for reproducibility across exports (not one-hot, per V1's simplicity).
    task_type_order = sorted(df["task_type"].unique())
    task_type_encoding = {t: i for i, t in enumerate(task_type_order)}

    # -- per-(robot, task) sequential features, computed once per group in time order --
    seq_feature_rows: dict[int, dict] = {}
    df_sorted = df.sort_values(["run_id", "robot_id", "task_id", "simulation_time"])
    for (run_id, robot_id, task_id), group in df_sorted.groupby(["run_id", "robot_id", "task_id"]):
        group = group.sort_values("simulation_time")
        prev_row = None
        edges_seen: set[str] = set()
        turn_count = 0
        curvature = 0.0
        stopped_seconds = 0.0
        for idx, row in group.iterrows():
            accel = 0.0
            if prev_row is not None:
                dt = row["simulation_time"] - prev_row["simulation_time"]
                if dt > 0:
                    accel = (row["speed"] - prev_row["speed"]) / dt
                    dyaw = (row["yaw"] - prev_row["yaw"] + 3.14159265) % (2 * 3.14159265) - 3.14159265
                    curvature += abs(dyaw)
                    if abs(dyaw) > TURN_THRESHOLD_RAD:
                        turn_count += 1
                    if row["speed"] < STOP_SPEED_MPS:
                        stopped_seconds += dt
            if row["current_edge_source"] and row["current_edge_target"]:
                edges_seen.add(canon_edge(row["current_edge_source"], row["current_edge_target"]))

            edge_congestion = None
            if row["current_edge_source"]:
                ekey = canon_edge(row["current_edge_source"], row["current_edge_target"])
                ctx = get_warehouse_context(session, layout_ids[run_id])
                edge_ctx = ctx.edges.get(ekey)
                occ = edge_occ.get((run_id, ekey, row["tick"]), 0)
                width = edge_ctx.width_m if edge_ctx else None
                capacity = max(1, int((width or ROBOT_DIAMETER_M) // ROBOT_DIAMETER_M))
                edge_congestion = occ / capacity

            seq_feature_rows[idx] = {
                "path_turn_count": turn_count,
                "path_curvature": curvature,
                "route_edge_count": len(edges_seen),
                "acceleration_mps2": accel,
                "waiting_time_so_far_s": stopped_seconds,
                "stop_count": 0,  # overwritten by the second pass below
                "edge_congestion_score": edge_congestion,
            }
            prev_row = row

    # stop_count: transitions into "stopped" (speed < STOP_SPEED_MPS) since task start -- computed
    # in a second, simpler pass since it needs a "was moving last sample" flag, not accumulated turn logic.
    for (run_id, robot_id, task_id), group in df_sorted.groupby(["run_id", "robot_id", "task_id"]):
        group = group.sort_values("simulation_time")
        was_stopped = False
        stop_count = 0
        for idx, row in group.iterrows():
            is_stopped = row["speed"] < STOP_SPEED_MPS
            if is_stopped and not was_stopped:
                stop_count += 1
            was_stopped = is_stopped
            seq_feature_rows[idx]["stop_count"] = stop_count

    seq_df = pd.DataFrame.from_dict(seq_feature_rows, orient="index")
    df = df.join(seq_df)

    # -- workload_count: other tasks assigned to this robot, active at this observation's sim_time --
    def _workload(row) -> int:
        mine = all_tasks[
            (all_tasks["run_id"] == row["run_id"])
            & (all_tasks["assigned_robot_id"] == row["robot_id"])
            & (all_tasks["task_id"] != row["task_id"])
        ]
        active = mine[
            (mine["final_status"].isin(["assigned", "in_progress"]))
            | ((mine["completion_time"].isna()) & (mine["release_time"] <= row["simulation_time"]))
        ]
        return len(active)

    df["workload_count"] = df.apply(_workload, axis=1)

    # -- historical_delay_factor: this robot's own avg completion time so far / fleet-wide avg so far --
    def _historical_delay_factor(row) -> float:
        past_completed = all_tasks[
            (all_tasks["run_id"] == row["run_id"])
            & (all_tasks["final_status"] == "completed")
            & (all_tasks["completion_time"] < row["simulation_time"])
        ]
        if past_completed.empty:
            return 1.0
        past_completed = past_completed.assign(duration=past_completed["completion_time"] - past_completed["release_time"])
        fleet_avg = past_completed["duration"].mean()
        mine = past_completed[past_completed["assigned_robot_id"] == row["robot_id"]]
        if mine.empty or fleet_avg <= 0:
            return 1.0
        return float(mine["duration"].mean() / fleet_avg)

    df["historical_delay_factor"] = df.apply(_historical_delay_factor, axis=1)

    df["max_speed_mps"] = df.apply(lambda r: robot_max_speed.get((r["run_id"], r["robot_id"])), axis=1)
    df["task_type_encoded"] = df["task_type"].map(task_type_encoding)
    df["source_zone_type"] = df["source_zone_id"]
    df["destination_zone_type"] = df["destination_zone_id"]
    df["destination_queue_depth"] = df.apply(
        lambda r: zone_occ.get((r["run_id"], r["destination_zone_type"], r["tick"]), 0), axis=1
    )
    df.rename(
        columns={
            "speed": "current_speed_mps",
            "priority": "task_priority",
            "planned_distance": "planned_path_length_m",
            "local_density": "local_traffic_density",
            "age_since_release_s": "task_age_s",
        },
        inplace=True,
    )

    feature_cols = [
        "run_id", "robot_id", "task_id", "simulation_time",
        "task_type", "source_zone_id", "destination_zone_id",
        "x", "y",
    ] + FEATURE_COLUMNS
    label_cols = ["label_remaining_time_s", "completion_time"]
    out = df[feature_cols + label_cols].copy()
    out["split"] = out["run_id"].map(split_for_run)

    assert (out["completion_time"] > out["simulation_time"]).all(), "leakage check failed: label timestamp must be strictly future"

    dataset_id = f"eta_{uuid.uuid4().hex[:12]}"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{dataset_id}.parquet"
    out.to_parquet(output_path, index=False)

    schema_path = out_dir / f"{dataset_id}.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "model": "eta",
                "feature_version": FEATURE_VERSION,
                "feature_columns": FEATURE_COLUMNS,
                "bookkeeping_columns": ["run_id", "robot_id", "task_id", "simulation_time", "task_type", "source_zone_id", "destination_zone_id", "x", "y"],
                "label_columns": label_cols,
                "label_definition": "remaining time (seconds) until task completion, observed while robot is en route",
                "dropped_from_v1": DROPPED_FROM_V1,
                "dropped_from_v1_reason": DROPPED_FROM_V1_REASON,
                "proxy_features": PROXY_FEATURE_NOTES,
                "task_type_encoding": task_type_encoding,
                "source_run_ids": run_ids,
                "row_count": len(out),
                "split_counts": out["split"].value_counts().to_dict(),
            },
            indent=2,
        )
    )

    session.add(
        ModelDatasetRegistry(
            dataset_id=dataset_id,
            model_name="eta",
            feature_version=FEATURE_VERSION,
            label_definition={"definition": "remaining_time_s = completion_time - simulation_time", "horizon_s": None},
            horizon_s=None,
            source_run_ids=run_ids,
            output_path=str(output_path),
            status="ready",
        )
    )
    session.commit()

    return ETADatasetResult(dataset_id=dataset_id, output_path=str(output_path), n_rows=len(out), n_runs=len(run_ids))
