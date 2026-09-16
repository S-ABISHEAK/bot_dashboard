"""Conflict Predictor dataset -- frozen 24-feature schema (see the
FleetNet Edge-AI spec's Conflict Predictor section).

Ground truth is still ``ConflictEvent`` (a real, already-arbitrated
Karma/MD-PIBT ``(yielder, winner)`` pair), exactly as before -- one row
per (robot pair, observed snapshot); label = whether that pair appears
in a dependency edge within ``horizon_s`` strictly after the
observation.

Several frozen features have no persisted "planned route" to compute
the literal textbook definition from (only ``route_events.route_hash``/
``route_length_m`` are stored, never the actual edge sequence), so they
are honest, clearly-labeled proxies instead -- see
``PROXY_FEATURE_NOTES`` below. ``time_to_closest_approach_s`` /
``distance_at_closest_approach_m`` / ``path_intersection_flag`` /
``intersection_distance_m`` use constant-velocity extrapolation from
each robot's current ``(x, y, yaw, speed)`` -- a simple, honest
approximation that degrades at longer horizons if a robot is actively
replanning (documented once already this session, applies here too).
"""
from __future__ import annotations

import json
import math
import uuid
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.splits import split_for_run
from fleetnet_sim.datasets.warehouse_context import ROBOT_DIAMETER_M, canon_edge, get_warehouse_context

FEATURE_VERSION = "conflict_v2"
DEFAULT_HORIZON_S = 2.0
DEFAULT_PAIR_RADIUS_M = 8.0
DEFAULT_RECENT_WINDOW_S = 30.0
STOP_SPEED_MPS = 0.05
NEAR_COLLISION_M = 1.5  # ~2x robot diameter -- "closer than this counts as a near collision", a documented threshold not a frozen-spec-given one

FEATURE_COLUMNS = [
    "relative_distance_m", "relative_x_m", "relative_y_m", "relative_velocity_mps", "closing_speed_mps",
    "heading_difference_rad", "robot_a_speed_mps", "robot_b_speed_mps", "time_to_closest_approach_s",
    "distance_at_closest_approach_m", "path_intersection_flag", "intersection_distance_m", "shared_edge_flag",
    "shared_node_flag", "path_overlap_ratio", "eta_difference_s", "local_robot_density", "edge_occupancy_ratio",
    "queue_depth", "priority_difference", "previous_conflict_count", "previous_near_collision_count",
    "previous_waiting_time_s", "current_motion_state",
]
PROXY_FEATURE_NOTES = {
    "path_overlap_ratio": "Jaccard overlap of each robot's visited-edge set over the last recent_window_s (from current_edge_source/target samples), not the literal planned-future-route overlap (no persisted route/edge-sequence exists)",
    "eta_difference_s": "|remaining_distance / current_speed| difference between the pair, a rough ETA proxy from planned_distance - distance_travelled, not the ETA model's own prediction",
    "edge_occupancy_ratio": "occupancy/capacity of the pair's shared edge if shared_edge_flag, else robot A's own current edge",
    "queue_depth": "count of OTHER robots within pair_radius_m of the pair's midpoint with speed < STOP_SPEED_MPS (a local-area proxy, not one specific edge's queue)",
    "previous_near_collision_count": f"count of past observations (within recent_window_s) where this exact pair's distance was < {NEAR_COLLISION_M}m (a documented threshold, not a frozen-spec-given one)",
    "current_motion_state": "robot A's task_state (a convention -- this is a pairwise row, robot A/B labeling is otherwise arbitrary per pair)",
}


@dataclass
class ConflictDatasetResult:
    dataset_id: str
    output_path: str
    n_rows: int
    n_runs: int


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


def _load_conflict_events(session: Session, run_ids: list[str]) -> pd.DataFrame:
    q = text(
        "SELECT run_id, simulation_time, yielder_robot_id, winner_robot_id FROM conflict_events WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    return pd.read_sql(q, session.connection(), params={"run_ids": run_ids})


def _load_run_layout_ids(session: Session, run_ids: list[str]) -> dict[str, str]:
    q = text("SELECT run_id, layout_id FROM simulation_runs WHERE run_id IN :run_ids").bindparams(
        bindparam("run_ids", expanding=True)
    )
    return dict(session.execute(q, {"run_ids": run_ids}).all())


def _load_tasks(session: Session, run_ids: list[str]) -> pd.DataFrame:
    q = text(
        "SELECT run_id, task_id, priority, planned_distance FROM tasks WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    return pd.read_sql(q, session.connection(), params={"run_ids": run_ids})


def _load_edge_occupancy(session: Session, run_ids: list[str]) -> dict[tuple[str, str, int], int]:
    q = text(
        "SELECT run_id, tick, edge_source, edge_target, occupancy_count FROM edge_state_ts WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    df = pd.read_sql(q, session.connection(), params={"run_ids": run_ids})
    out: dict[tuple[str, str, int], int] = {}
    for row in df.itertuples(index=False):
        out[(row.run_id, canon_edge(row.edge_source, row.edge_target), row.tick)] = row.occupancy_count
    return out


def _pair_key(a: str, b: str) -> str:
    lo, hi = sorted((a, b))
    return f"{lo}|{hi}"


def _cpa(rax, ray, rvx, rvy) -> tuple[float | None, float | None]:
    """Constant-velocity closest-point-of-approach: given relative
    position (rax, ray) = b - a and relative velocity (rvx, rvy) = vb - va,
    return (time_to_cpa_s, distance_at_cpa_m). None if the pair is not
    closing (moving apart or stationary relative to each other) -- there
    is no meaningful future closest approach to report in that case."""
    speed2 = rvx * rvx + rvy * rvy
    if speed2 < 1e-9:
        return None, None
    t_cpa = -(rax * rvx + ray * rvy) / speed2
    if t_cpa <= 0:
        return None, None
    dx, dy = rax + rvx * t_cpa, ray + rvy * t_cpa
    return t_cpa, math.hypot(dx, dy)


def _segment_intersection(ax, ay, adx, ady, bx, by, bdx, bdy) -> tuple[bool, float | None]:
    """Do segments A=[(ax,ay), (ax+adx, ay+ady)] and B=[(bx,by), (bx+bdx, by+bdy)]
    intersect? Returns (flag, distance from A's start to the intersection
    point along A, if any)."""
    denom = adx * bdy - ady * bdx
    if abs(denom) < 1e-9:
        return False, None
    t = ((bx - ax) * bdy - (by - ay) * bdx) / denom
    u = ((bx - ax) * ady - (by - ay) * adx) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        ix, iy = ax + t * adx, ay + t * ady
        return True, math.hypot(ix - ax, iy - ay)
    return False, None


def build_conflict_dataset(
    session: Session,
    run_ids: list[str],
    output_dir: str,
    horizon_s: float = DEFAULT_HORIZON_S,
    pair_radius_m: float = DEFAULT_PAIR_RADIUS_M,
    recent_window_s: float = DEFAULT_RECENT_WINDOW_S,
) -> ConflictDatasetResult:
    states_q = text(
        "SELECT run_id, tick, simulation_time, robot_id, x, y, yaw, speed, task_id, task_state, "
        "replan_count, distance_travelled, current_edge_source, current_edge_target, current_node_id "
        "FROM robot_state_ts WHERE run_id IN :run_ids"
    ).bindparams(bindparam("run_ids", expanding=True))
    states = pd.read_sql(states_q, session.connection(), params={"run_ids": run_ids})
    if states.empty:
        raise ValueError("no robot_state_ts rows found for the given run_ids")

    conflict_df = _load_conflict_events(session, run_ids)
    conflict_times_by_run_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in conflict_df.itertuples(index=False):
        key = (row.run_id, _pair_key(row.yielder_robot_id, row.winner_robot_id))
        conflict_times_by_run_pair[key].append(row.simulation_time)
    for k in conflict_times_by_run_pair:
        conflict_times_by_run_pair[k].sort()

    layout_ids = _load_run_layout_ids(session, run_ids)
    tasks_df = _load_tasks(session, run_ids)
    task_priority = {(r.run_id, r.task_id): r.priority for r in tasks_df.itertuples(index=False)}
    task_planned_distance = {(r.run_id, r.task_id): r.planned_distance for r in tasks_df.itertuples(index=False)}
    edge_occupancy = _load_edge_occupancy(session, run_ids)

    rows = []
    for run_id, run_states in states.groupby("run_id"):
        ctx = get_warehouse_context(session, layout_ids[run_id])
        # Per-robot recent history, built incrementally in ascending tick order.
        robot_edge_history: dict[str, list[tuple[float, str]]] = defaultdict(list)  # for path_overlap
        robot_stopped_seconds: dict[str, list[tuple[float, float]]] = defaultdict(list)  # (time, seconds_stopped_this_step)
        robot_last_time: dict[str, float] = {}
        pair_distance_history: dict[str, list[tuple[float, float]]] = defaultdict(list)  # for near-collision lookback

        for tick, snapshot in run_states.groupby("tick"):
            sim_time = float(snapshot["simulation_time"].iloc[0])
            recs = snapshot.to_dict("records")

            # -- update per-robot histories once per robot per tick (not per pair) --
            for r in recs:
                rid = r["robot_id"]
                dt = sim_time - robot_last_time.get(rid, sim_time)
                stopped_seconds = dt if r["speed"] < STOP_SPEED_MPS else 0.0
                robot_stopped_seconds[rid].append((sim_time, stopped_seconds))
                robot_stopped_seconds[rid] = [(t, s) for t, s in robot_stopped_seconds[rid] if sim_time - t <= recent_window_s]
                robot_last_time[rid] = sim_time
                if r["current_edge_source"] and r["current_edge_target"]:
                    ekey = canon_edge(r["current_edge_source"], r["current_edge_target"])
                    robot_edge_history[rid].append((sim_time, ekey))
                    robot_edge_history[rid] = [(t, e) for t, e in robot_edge_history[rid] if sim_time - t <= recent_window_s]

            for ra, rb in combinations(recs, 2):
                d = _dist(ra["x"], ra["y"], rb["x"], rb["y"])
                if d > pair_radius_m:
                    continue
                pkey = _pair_key(ra["robot_id"], rb["robot_id"])

                vax, vay = ra["speed"] * math.cos(ra["yaw"]), ra["speed"] * math.sin(ra["yaw"])
                vbx, vby = rb["speed"] * math.cos(rb["yaw"]), rb["speed"] * math.sin(rb["yaw"])
                rel_x, rel_y = rb["x"] - ra["x"], rb["y"] - ra["y"]
                rel_vx, rel_vy = vbx - vax, vby - vay
                closing_speed = -(rel_x * rel_vx + rel_y * rel_vy) / max(d, 1e-6)
                t_cpa, d_cpa = _cpa(rel_x, rel_y, rel_vx, rel_vy)

                intersects, intersect_dist = _segment_intersection(
                    ra["x"], ra["y"], vax * horizon_s, vay * horizon_s,
                    rb["x"], rb["y"], vbx * horizon_s, vby * horizon_s,
                )

                same_edge = (
                    bool(ra["current_edge_source"]) and bool(rb["current_edge_source"])
                    and canon_edge(ra["current_edge_source"], ra["current_edge_target"])
                    == canon_edge(rb["current_edge_source"], rb["current_edge_target"])
                )
                same_node = bool(ra["current_node_id"]) and ra["current_node_id"] == rb["current_node_id"]

                # path_overlap_ratio: Jaccard overlap of each robot's recent visited-edge set
                edges_a = {e for _, e in robot_edge_history.get(ra["robot_id"], [])}
                edges_b = {e for _, e in robot_edge_history.get(rb["robot_id"], [])}
                union = edges_a | edges_b
                overlap_ratio = len(edges_a & edges_b) / len(union) if union else 0.0

                # eta_difference_s: rough ETA proxy from remaining planned distance / current speed
                def _rough_eta(r):
                    planned = task_planned_distance.get((run_id, r["task_id"]))
                    if planned is None or r["speed"] < 1e-6:
                        return None
                    remaining = max(0.0, planned - r["distance_travelled"])
                    return remaining / r["speed"]

                eta_a, eta_b = _rough_eta(ra), _rough_eta(rb)
                eta_diff = abs(eta_a - eta_b) if (eta_a is not None and eta_b is not None) else None

                priority_a = task_priority.get((run_id, ra["task_id"]))
                priority_b = task_priority.get((run_id, rb["task_id"]))
                priority_diff = abs(priority_a - priority_b) if (priority_a is not None and priority_b is not None) else None

                # local_robot_density: avg of each robot's own neighbor count within pair_radius_m
                def _density(target_id, tx, ty):
                    return sum(
                        1 for r in recs if r["robot_id"] != target_id and _dist(tx, ty, r["x"], r["y"]) <= pair_radius_m
                    )

                density_a = _density(ra["robot_id"], ra["x"], ra["y"])
                density_b = _density(rb["robot_id"], rb["x"], rb["y"])
                local_density = (density_a + density_b) / 2.0

                # edge_occupancy_ratio: shared edge if same_edge, else robot A's own edge
                edge_for_ratio = None
                if same_edge and ra["current_edge_source"]:
                    edge_for_ratio = canon_edge(ra["current_edge_source"], ra["current_edge_target"])
                elif ra["current_edge_source"]:
                    edge_for_ratio = canon_edge(ra["current_edge_source"], ra["current_edge_target"])
                occ_ratio = None
                if edge_for_ratio:
                    edge_ctx = ctx.edges.get(edge_for_ratio)
                    occ = edge_occupancy.get((run_id, edge_for_ratio, tick), 0)
                    width = edge_ctx.width_m if edge_ctx else None
                    capacity = max(1, int((width or ROBOT_DIAMETER_M) // ROBOT_DIAMETER_M))
                    occ_ratio = occ / capacity

                # queue_depth: other nearby robots (within pair_radius_m of the pair midpoint) that are stopped
                mid_x, mid_y = (ra["x"] + rb["x"]) / 2, (ra["y"] + rb["y"]) / 2
                queue_depth = sum(
                    1 for r in recs
                    if r["robot_id"] not in (ra["robot_id"], rb["robot_id"])
                    and _dist(mid_x, mid_y, r["x"], r["y"]) <= pair_radius_m
                    and r["speed"] < STOP_SPEED_MPS
                )

                # previous_* backward-looking counts (strictly before this observation)
                conflict_times = conflict_times_by_run_pair.get((run_id, pkey), [])
                previous_conflict_count = bisect_left(conflict_times, sim_time)
                past_distances = pair_distance_history.get(pkey, [])
                previous_near_collision_count = sum(
                    1 for t, dd in past_distances if sim_time - t <= recent_window_s and dd < NEAR_COLLISION_M
                )
                previous_waiting_time_s = sum(
                    s for t, s in robot_stopped_seconds.get(ra["robot_id"], []) if sim_time - t <= recent_window_s
                ) + sum(
                    s for t, s in robot_stopped_seconds.get(rb["robot_id"], []) if sim_time - t <= recent_window_s
                )

                label = _pair_conflicts_within_horizon(conflict_times, sim_time, horizon_s)

                rows.append(
                    {
                        "run_id": run_id,
                        "simulation_time": sim_time,
                        "robot_a_id": ra["robot_id"],
                        "robot_b_id": rb["robot_id"],
                        "relative_distance_m": d,
                        "relative_x_m": rel_x,
                        "relative_y_m": rel_y,
                        "relative_velocity_mps": math.hypot(rel_vx, rel_vy),
                        "closing_speed_mps": closing_speed,
                        "heading_difference_rad": (ra["yaw"] - rb["yaw"] + math.pi) % (2 * math.pi) - math.pi,
                        "robot_a_speed_mps": ra["speed"],
                        "robot_b_speed_mps": rb["speed"],
                        "time_to_closest_approach_s": t_cpa,
                        "distance_at_closest_approach_m": d_cpa,
                        "path_intersection_flag": bool(intersects),
                        "intersection_distance_m": intersect_dist,
                        "shared_edge_flag": same_edge,
                        "shared_node_flag": same_node,
                        "path_overlap_ratio": overlap_ratio,
                        "eta_difference_s": eta_diff,
                        "local_robot_density": local_density,
                        "edge_occupancy_ratio": occ_ratio,
                        "queue_depth": queue_depth,
                        "priority_difference": priority_diff,
                        "previous_conflict_count": previous_conflict_count,
                        "previous_near_collision_count": previous_near_collision_count,
                        "previous_waiting_time_s": previous_waiting_time_s,
                        "current_motion_state": ra["task_state"],
                        "label_conflict_within_horizon": label,
                    }
                )
                pair_distance_history[pkey].append((sim_time, d))
                pair_distance_history[pkey] = [
                    (t, dd) for t, dd in pair_distance_history[pkey] if sim_time - t <= recent_window_s
                ]

    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("no robot pairs fell within pair_radius_m across the given run_ids")
    out["split"] = out["run_id"].map(split_for_run)

    dataset_id = f"conflict_{uuid.uuid4().hex[:12]}"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{dataset_id}.parquet"
    out.to_parquet(output_path, index=False)

    schema_path = out_dir / f"{dataset_id}.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "model": "conflict",
                "feature_version": FEATURE_VERSION,
                "feature_columns": FEATURE_COLUMNS,
                "bookkeeping_columns": ["run_id", "simulation_time", "robot_a_id", "robot_b_id"],
                "label_columns": ["label_conflict_within_horizon"],
                "label_definition": f"pair enters a Karma/MD-PIBT-arbitrated conflict within {horizon_s}s of observation",
                "horizon_s": horizon_s,
                "pair_radius_m": pair_radius_m,
                "recent_window_s": recent_window_s,
                "near_collision_threshold_m": NEAR_COLLISION_M,
                "proxy_features": PROXY_FEATURE_NOTES,
                "source_run_ids": run_ids,
                "row_count": len(out),
                "positive_rate": float(out["label_conflict_within_horizon"].mean()),
                "split_counts": out["split"].value_counts().to_dict(),
            },
            indent=2,
        )
    )

    from fleetnet_sim.storage.models import ModelDatasetRegistry

    session.add(
        ModelDatasetRegistry(
            dataset_id=dataset_id,
            model_name="conflict",
            feature_version=FEATURE_VERSION,
            label_definition={"horizon_s": horizon_s, "pair_radius_m": pair_radius_m},
            horizon_s=horizon_s,
            source_run_ids=run_ids,
            output_path=str(output_path),
            status="ready",
        )
    )
    session.commit()

    return ConflictDatasetResult(dataset_id=dataset_id, output_path=str(output_path), n_rows=len(out), n_runs=len(run_ids))


def _pair_conflicts_within_horizon(times: list[float], t_obs: float, horizon_s: float) -> bool:
    lo = bisect_right(times, t_obs)
    hi = bisect_right(times, t_obs + horizon_s)
    return hi > lo
