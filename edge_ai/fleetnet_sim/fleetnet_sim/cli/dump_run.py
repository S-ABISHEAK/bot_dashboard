"""Dump every telemetry table for one run_id to JSON files -- the full
recorded data behind a run, not just the GET /api/runs/{id} summary.
Usage: .venv/bin/python -m fleetnet_sim.cli.dump_run <run_id> [out_dir]
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

DEFAULT_DSN = "postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim"

TABLES = [
    "simulation_runs",
    "run_metrics",
    "robot_state_ts",
    "task_lifecycle_events",
    "conflict_events",
    "congestion_events",
    "communication_events",
    "algorithm_events",
    "route_events",
    "edge_state_ts",
    "node_state_ts",
    "zone_state_ts",
]


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: dump_run.py <run_id> [out_dir] [--dsn DSN]", file=sys.stderr)
        raise SystemExit(1)
    run_id = sys.argv[1]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path(f"./run_dump_{run_id}")
    dsn = DEFAULT_DSN
    if "--dsn" in sys.argv:
        dsn = sys.argv[sys.argv.index("--dsn") + 1]

    out_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(dsn)
    with engine.connect() as conn:
        for table in TABLES:
            try:
                rows = conn.execute(text(f"SELECT * FROM {table} WHERE run_id = :rid ORDER BY 1"), {"rid": run_id}).mappings().all()
            except Exception as e:
                print(f"skip {table}: {e}", file=sys.stderr)
                continue
            data = [dict(r) for r in rows]
            path = out_dir / f"{table}.json"
            path.write_text(json.dumps(data, default=_default, indent=2))
            print(f"{table}: {len(data)} rows -> {path}")


if __name__ == "__main__":
    main()
