"""Runs a launched simulation in a background thread so the FastAPI
event loop stays responsive to poll requests while it executes. Not a
subprocess (heavier, harder to report status from) and not
asyncio-native (the whole engine/telemetry/SQLAlchemy stack is
synchronous — rewriting it would be reimplementation, which this project
avoids everywhere else). A thread is safe here because psycopg2 releases
the GIL during I/O, so `_run_simulation`'s DB-bound work doesn't starve
the event loop.

`JobRegistry` is a purely in-memory, low-latency cache of actively
launched jobs — it does NOT survive a server restart, and that's fine:
`simulation_runs.status` in Postgres is the actual source of truth for
anything that matters (see `GET /api/runs/{run_id}`); this registry only
exists so `GET /api/simulate/{run_id}/status` doesn't need a DB round
trip for a tight poll loop, and so it can report status even in the
brief window before the `SimulationRun` row is committed at all.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from fleetnet_sim.cli.main import _run_simulation
from fleetnet_sim.config.schema import ExperimentConfig

MAX_CONCURRENT_JOBS = 2


@dataclass
class JobState:
    run_id: str
    status: str = "queued"  # queued | running | completed | failed
    error: str | None = None


class ConcurrencyLimitError(Exception):
    pass


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def _active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))

    def start(self, config: ExperimentConfig) -> JobState:
        with self._lock:
            if self._active_count() >= MAX_CONCURRENT_JOBS:
                raise ConcurrencyLimitError(
                    f"{MAX_CONCURRENT_JOBS} simulations already running — wait for one to finish before launching another"
                )
            job = JobState(run_id=config.run_id, status="queued")
            self._jobs[config.run_id] = job

        thread = threading.Thread(target=self._run, args=(job, config), daemon=True)
        thread.start()
        return job

    def _run(self, job: JobState, config: ExperimentConfig) -> None:
        job.status = "running"
        try:
            # schema/hypertables are already ensured once at server
            # startup (dashboard/server.py::run_server) -- skip the
            # redundant CREATE TABLE/create_hypertable calls per launch.
            result = _run_simulation(config, skip_schema_init=True)
            # _run_simulation already claims never to raise -- but don't
            # trust that blindly here: if it somehow did, the `except`
            # below still marks the job failed rather than leaving it
            # stuck at "running" forever.
            job.status = result["status"]
            job.error = result.get("error")
        except Exception as exc:  # pragma: no cover - defensive, see docstring
            job.status = "failed"
            job.error = str(exc)

    def get(self, run_id: str) -> JobState | None:
        return self._jobs.get(run_id)
