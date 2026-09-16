"""Congestion Predictor dataset -- frozen 25-feature schema (see the
FleetNet Edge-AI spec's Congestion Predictor section).

Built from ``edge_state_ts`` (one row per sampled (edge, tick)) plus:
static warehouse geometry/graph context (``warehouse_context.py``,
edge length/width/degree/centrality/bottleneck score), the run's fleet
config (``robots.max_speed_mps``, as the free-flow speed reference),
and ``robot_state_ts``'s ``current_edge_source``/``current_edge_target``
(to reconstruct which robots occupied which edge at each sampled tick,
needed for several features ``edge_state_ts`` alone doesn't carry).

Ground truth is still derived directly from ``occupancy_count`` exactly
as before -- a congestion event is "``occupancy_count`` reaches
``congestion_occupancy_threshold`` within ``horizon_s`` strictly after
the observation." Same no-future-leakage discipline: every ``recent_*``
feature below looks strictly *backward* from the observation tick; only
the label looks forward.

Two features have no real mechanic to derive from in this simulation and
are documented rather than faked:
- ``blocked_edge_flag`` / ``blockage_duration_s`` -- the engine has no
  dynamic edge-blockage mechanic, so these are legitimately always
  0/False for every run today (not fabricated -- correctly reflecting
  that no edge is ever actually blocked in this simulator yet).

Several other features are honest, clearly-labeled *proxies* rather
than the literal textbook definition, because the underlying planned
route isn't persisted per-robot (only ``route_events.route_hash``/
``route_length_m``, not the actual edge sequence) -- see each
docstring note below (``path_overlap_count/ratio``, ``incoming_robot_count``,
``recent_waiting_time_s``, ``recent_delay_s``).
"""
from __future__ import annotations

import json
import uuid
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.splits import split_for_run
from fleetnet_sim.datasets.warehouse_context import ROBOT_DIAMETER_M, canon_edge, get_warehouse_context
from fleetnet_sim.storage.models import ModelDatasetRegistry

FEATURE_VERSION = "congestion_v2"
DEFAULT_HORIZON_S = 5.0
DEFAULT_CONGESTION_OCCUPANCY_THRESHOLD = 2
DEFAULT_RECENT_WINDOW_S = 30.0
STOP_SPEED_MPS = 0.05  # below this, a robot on the edge counts as "queued"

FEATURE_COLUMNS = [
    "edge_length_m", "edge_width_m", "edge_occupancy_count", "edge_occupancy_ratio",
    "nearby_robot_count", "incoming_robot_count", "queue_depth", "average_edge_speed_mps",
    "speed_variance", "velocity_deficit_ratio", "path_overlap_count", "path_overlap_ratio",
    "shared_edge_flag", "shared_node_flag", "node_out_degree", "node_centrality",
    "bottleneck_risk_score", "blocked_edge_flag", "blockage_duration_s", "recent_waiting_time_s",
    "recent_delay_s", "recent_congestion_score", "occupancy_change_rate", "incoming_flow_rate",
    "outgoing_flow_rate",
]
DROPPED_FROM_V1: list[str] = []  # congestion has no undeliverable features, unlike ETA


@dataclass
class CongestionDatasetResult:
    dataset_id: str
    output_path: str
    n_rows: int
    n_runs: int


def _run_layout_ids(session: Session, run_ids: list[str]) -> dict[str, str]:
    q = text("SELECT run_id, layout_id FROM simulation_runs WHERE run_id IN :run_ids").bindparams(
        bindparam("run_ids", expanding=True)
    )
    return dict(session.execute(q, {"run_ids": run_ids}).all())


def _run_max_speed(session: Session, run_ids: list[str]) -> dict[str, float]:
    q = text("SELECT run_id, MAX(max_speed_mps) AS v FROM robots WHERE run_id IN :run_ids GROUP BY run_id").bindparams(
        bindparam("run_ids", expanding=True)
    )
    result = dict(session.execute(q, {"run_ids": run_ids}).all())
    return {k: float(v) for k, v in result.items() if v}


def _run_robot_count(session: Session, run_ids: list[str]) -> dict[str, int]:
    q = text("SELECT run_id, COUNT(*) AS n FROM robots WHERE run_id IN :run_ids GROUP BY run_id").bindparams(
        bindparam("run_ids", expanding=True)
    )
    return {k: int(v) for k, v in session.execute(q, {"run_ids": run_ids}).all()}


def _robot_edge_assignments(session: Session, run_ids: list[str]) -> pd.DataFrame:
    q = text(
        "SELECT run_id, tick, simulation_time, robot_id, speed, current_edge_source, current_edge_target "
        "FROM robot_state_ts WHERE run_id IN :run_ids AND current_edge_source IS NOT NULL AND current_edge_target IS NOT NULL"
    ).bindparams(bindparam("run_ids", expanding=True))
    df = pd.read_sql(q, session.connection(), params={"run_ids": run_ids})
    if df.empty:
        return df
    df["edge_key"] = [canon_edge(a, b) for a, b in zip(df["current_edge_source"], df["current_edge_target"])]
    return df


def build_congestion_dataset(
    session: Session,
    run_ids: list[str],
    output_dir: str,
    horizon_s: float = DEFAULT_HORIZON_S,
    congestion_occupancy_threshold: int = DEFAULT_CONGESTION_OCCUPANCY_THRESHOLD,
    recent_window_s: float = DEFAULT_RECENT_WINDOW_S,
) -> CongestionDatasetResult:
    q = text(
        "SELECT run_id, tick, simulation_time, edge_source, edge_target, "
        "occupancy_count, avg_speed, min_speed, max_speed FROM edge_state_ts "
        "WHERE run_id IN :run_ids ORDER BY run_id, edge_source, edge_target, simulation_time"
    ).bindparams(bindparam("run_ids", expanding=True))
    df = pd.read_sql(q, session.connection(), params={"run_ids": run_ids})
    if df.empty:
        raise ValueError("no edge_state_ts rows found for the given run_ids")
    df["edge_key"] = [canon_edge(a, b) for a, b in zip(df["edge_source"], df["edge_target"])]

    layout_ids = _run_layout_ids(session, run_ids)
    max_speed_ref = _run_max_speed(session, run_ids)
    robot_counts = _run_robot_count(session, run_ids)
    robot_edges = _robot_edge_assignments(session, run_ids)

    # Per (run_id, edge_key, tick) -> set of robot_ids present, and their speeds.
    robots_by_edge_tick: dict[tuple[str, str, int], list[tuple[str, float]]] = defaultdict(list)
    if not robot_edges.empty:
        for rec in robot_edges.itertuples(index=False):
            robots_by_edge_tick[(rec.run_id, rec.edge_key, rec.tick)].append((rec.robot_id, rec.speed))

    # Per (run_id, edge_key) sorted list of (simulation_time, occupancy_count) for
    # the forward-looking label -- unchanged from v1.
    series: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    for row in df.itertuples(index=False):
        series[(row.run_id, row.edge_key)].append((row.simulation_time, row.occupancy_count))

    rows = []
    df_sorted = df.sort_values(["run_id", "edge_key", "simulation_time"])
    for (run_id, edge_key), group in df_sorted.groupby(["run_id", "edge_key"]):
        ctx = get_warehouse_context(session, layout_ids[run_id])
        edge_ctx = ctx.edges.get(edge_key)
        neighbor_keys = ctx.edge_neighbors.get(edge_key, set())
        speed_ref = max_speed_ref.get(run_id, 1.5)  # 1.5 m/s: config/schema.py's FleetConfig default, used only if robots table is empty

        times_occ = series[(run_id, edge_key)]
        times = [t for t, _ in times_occ]
        occs = [o for _, o in times_occ]

        # Build this edge's own (time, robot_id_set) history, sorted.
        own_history: list[tuple[float, int, set]] = []
        for rec in group.itertuples(index=False):
            robot_speeds = robots_by_edge_tick.get((run_id, edge_key, rec.tick), [])
            own_history.append((rec.simulation_time, rec.tick, {rid for rid, _ in robot_speeds}))
        own_history.sort(key=lambda t: t[0])
        own_times = [t for t, _, _ in own_history]

        prev_occupancy = None
        prev_robot_set: set = set()
        recent_label_hist: list[tuple[float, bool]] = []  # (time, was_congested_now) for recent_congestion_score
        recent_deficit_hist: list[tuple[float, float]] = []  # (time, velocity_deficit_ratio) for recent_delay_s
        recent_queue_hist: list[tuple[float, int]] = []  # (time, queue_depth) for recent_waiting_time_s
        recent_robot_seen: dict[str, float] = {}  # robot_id -> last time seen on this edge, for path_overlap lookback

        for rec in group.itertuples(index=False):
            t_obs = rec.simulation_time
            robot_speeds = robots_by_edge_tick.get((run_id, edge_key, rec.tick), [])
            robot_ids_now = {rid for rid, _ in robot_speeds}
            speeds_now = [s for _, s in robot_speeds]

            dt_sample = t_obs - own_times[bisect_left(own_times, t_obs) - 1] if bisect_left(own_times, t_obs) > 0 else None

            # -- occupancy / capacity --
            width = edge_ctx.width_m if edge_ctx else None
            capacity = max(1, int((width or ROBOT_DIAMETER_M) // ROBOT_DIAMETER_M))
            occupancy_ratio = rec.occupancy_count / capacity

            # -- neighboring-edge aggregation --
            nearby_count = sum(
                robots_by_edge_tick.get((run_id, nk, rec.tick), []).__len__() for nk in neighbor_keys
            )

            # -- incoming/outgoing (proxy: newly-arrived / newly-departed robot ids since the previous sampled tick on THIS edge) --
            incoming_ids = robot_ids_now - prev_robot_set
            outgoing_ids = prev_robot_set - robot_ids_now
            incoming_count = len(incoming_ids)
            outgoing_count = len(outgoing_ids)
            incoming_rate = incoming_count / dt_sample if dt_sample else 0.0
            outgoing_rate = outgoing_count / dt_sample if dt_sample else 0.0

            # -- queue / speed stats --
            queue_depth = sum(1 for s in speeds_now if s < STOP_SPEED_MPS)
            speed_var = float(pd.Series(speeds_now).var(ddof=0)) if len(speeds_now) > 1 else 0.0
            velocity_deficit = max(0.0, min(1.0, (speed_ref - rec.avg_speed) / speed_ref)) if speed_ref > 0 else 0.0

            # -- path_overlap: distinct robots seen on this edge within recent_window_s (proxy for planned-route overlap; no persisted route/edge-sequence exists to compute the literal definition) --
            for rid in robot_ids_now:
                recent_robot_seen[rid] = t_obs
            for rid in list(recent_robot_seen):
                if t_obs - recent_robot_seen[rid] > recent_window_s:
                    del recent_robot_seen[rid]
            path_overlap_count = len(recent_robot_seen)

            # -- occupancy_change_rate: proper rate, not a raw per-tick delta --
            occ_rate = (rec.occupancy_count - prev_occupancy) / dt_sample if (prev_occupancy is not None and dt_sample) else 0.0

            # -- recent_* backward-looking windows (strictly t <= t_obs) --
            recent_label_hist.append((t_obs, rec.occupancy_count >= congestion_occupancy_threshold))
            recent_deficit_hist.append((t_obs, velocity_deficit))
            recent_queue_hist.append((t_obs, queue_depth))
            cutoff = t_obs - recent_window_s
            recent_label_hist[:] = [(t, v) for t, v in recent_label_hist if t >= cutoff]
            recent_deficit_hist[:] = [(t, v) for t, v in recent_deficit_hist if t >= cutoff]
            recent_queue_hist[:] = [(t, v) for t, v in recent_queue_hist if t >= cutoff]
            recent_congestion_score = sum(v for _, v in recent_label_hist) / len(recent_label_hist) if recent_label_hist else 0.0
            # time-equivalent (robot-seconds) of velocity deficit / queued-robot presence accumulated recently
            recent_delay_s = sum(v * dt_sample for _, v in recent_deficit_hist) if dt_sample else 0.0
            recent_waiting_time_s = sum(v * dt_sample for _, v in recent_queue_hist) if dt_sample else 0.0

            # -- forward-looking label (unchanged definition from v1) --
            lo = bisect_right(times, t_obs)
            hi = bisect_right(times, t_obs + horizon_s)
            future_occs = occs[lo:hi]
            label = any(o >= congestion_occupancy_threshold for o in future_occs)

            rows.append(
                {
                    "run_id": run_id,
                    "tick": rec.tick,
                    "simulation_time": t_obs,
                    "edge_source": rec.edge_source,
                    "edge_target": rec.edge_target,
                    "edge_length_m": edge_ctx.length_m if edge_ctx else None,
                    "edge_width_m": edge_ctx.width_m if edge_ctx else None,
                    "edge_occupancy_count": rec.occupancy_count,
                    "edge_occupancy_ratio": occupancy_ratio,
                    "nearby_robot_count": nearby_count,
                    "incoming_robot_count": incoming_count,
                    "queue_depth": queue_depth,
                    "average_edge_speed_mps": rec.avg_speed,
                    "speed_variance": speed_var,
                    "velocity_deficit_ratio": velocity_deficit,
                    "path_overlap_count": path_overlap_count,
                    "path_overlap_ratio": path_overlap_count / max(robot_counts.get(run_id, 1), 1),
                    "shared_edge_flag": edge_ctx.shared_edge_flag if edge_ctx else False,
                    "shared_node_flag": edge_ctx.shared_node_flag if edge_ctx else False,
                    "node_out_degree": edge_ctx.node_out_degree if edge_ctx else 0,
                    "node_centrality": edge_ctx.node_centrality if edge_ctx else 0.0,
                    "bottleneck_risk_score": edge_ctx.bottleneck_risk_score if edge_ctx else 0.0,
                    "blocked_edge_flag": False,
                    "blockage_duration_s": 0.0,
                    "recent_waiting_time_s": recent_waiting_time_s,
                    "recent_delay_s": recent_delay_s,
                    "recent_congestion_score": recent_congestion_score,
                    "occupancy_change_rate": occ_rate,
                    "incoming_flow_rate": incoming_rate,
                    "outgoing_flow_rate": outgoing_rate,
                    "label_congestion_within_horizon": bool(label),
                }
            )
            prev_occupancy = rec.occupancy_count
            prev_robot_set = robot_ids_now

    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("no edge_state_ts observations produced dataset rows")
    out["split"] = out["run_id"].map(split_for_run)

    dataset_id = f"congestion_{uuid.uuid4().hex[:12]}"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{dataset_id}.parquet"
    out.to_parquet(output_path, index=False)

    schema_path = out_dir / f"{dataset_id}.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "model": "congestion",
                "feature_version": FEATURE_VERSION,
                "feature_columns": FEATURE_COLUMNS,
                "bookkeeping_columns": ["run_id", "tick", "simulation_time", "edge_source", "edge_target"],
                "label_columns": ["label_congestion_within_horizon"],
                "label_definition": (
                    f"this edge's occupancy_count reaches >= {congestion_occupancy_threshold} "
                    f"simultaneous robots within {horizon_s}s of observation"
                ),
                "horizon_s": horizon_s,
                "congestion_occupancy_threshold": congestion_occupancy_threshold,
                "recent_window_s": recent_window_s,
                "always_zero_features": ["blocked_edge_flag", "blockage_duration_s"],
                "always_zero_reason": "no dynamic edge-blockage mechanic exists in the engine yet -- honestly always false, not fabricated",
                "proxy_features": {
                    "path_overlap_count": "distinct robots seen on this edge within recent_window_s (no persisted per-robot route/edge-sequence exists for the literal planned-path definition)",
                    "path_overlap_ratio": "path_overlap_count normalized by the run's total robot count",
                    "incoming_robot_count": "robot ids newly present on this edge since the previous sampled tick (not direction-of-travel inferred)",
                    "recent_delay_s": "robot-seconds of velocity-deficit accumulated on this edge within recent_window_s",
                    "recent_waiting_time_s": "robot-seconds of queued (near-zero-speed) presence on this edge within recent_window_s",
                },
                "source_run_ids": run_ids,
                "row_count": len(out),
                "positive_rate": float(out["label_congestion_within_horizon"].mean()),
                "split_counts": out["split"].value_counts().to_dict(),
            },
            indent=2,
        )
    )

    session.add(
        ModelDatasetRegistry(
            dataset_id=dataset_id,
            model_name="congestion",
            feature_version=FEATURE_VERSION,
            label_definition={"horizon_s": horizon_s, "congestion_occupancy_threshold": congestion_occupancy_threshold},
            horizon_s=horizon_s,
            source_run_ids=run_ids,
            output_path=str(output_path),
            status="ready",
        )
    )
    session.commit()

    return CongestionDatasetResult(dataset_id=dataset_id, output_path=str(output_path), n_rows=len(out), n_runs=len(run_ids))
