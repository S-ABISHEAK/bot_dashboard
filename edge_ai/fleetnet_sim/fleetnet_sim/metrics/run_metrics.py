"""Run-level metric aggregation (Section 18, thin-slice core subset:
task throughput/completion, travel/waiting, replans, conflicts).
Computed from the engine's final in-memory state at run end — a
separate, DB-driven aggregation (recomputing from stored telemetry
rather than in-memory state) is the natural extension once the full
event set lands, but this already satisfies "every run has queryable
run_metrics" for the thin slice.
"""
from __future__ import annotations

import statistics


def compute_run_metrics(engine) -> dict:
    records = list(engine.task_records.values())
    completed = [r for r in records if r.final_status == "completed"]
    durations = [
        (r.completion_time - r.assignment_time)
        for r in completed
        if r.completion_time is not None and r.assignment_time is not None
    ]
    distances = [r.actual_distance for r in completed]
    replans = [r.replan_count for r in completed]

    def pct(xs: list[float], p: float) -> float | None:
        if not xs:
            return None
        s = sorted(xs)
        idx = min(len(s) - 1, int(p * len(s)))
        return s[idx]

    return {
        "sim_time_s": engine.clock.simulation_time,
        "task": {
            "created": len(records),
            "completed": len(completed),
            "throughput_per_min": len(completed) / max(engine.clock.simulation_time, 1e-9) * 60.0,
            "mean_completion_time_s": statistics.fmean(durations) if durations else None,
            "median_completion_time_s": statistics.median(durations) if durations else None,
            "p95_completion_time_s": pct(durations, 0.95),
        },
        "travel": {
            "mean_distance_m": statistics.fmean(distances) if distances else None,
        },
        "planning": {
            "total_replans": sum(a.replan_count for a in engine.agents.values()),
            "mean_replans_per_robot": statistics.fmean([a.replan_count for a in engine.agents.values()]) if engine.agents else None,
        },
        "safety": {
            "collision_count": engine.metrics.collision_count,
        },
        "fleet": {
            "robot_count": len(engine.agents),
        },
    }
