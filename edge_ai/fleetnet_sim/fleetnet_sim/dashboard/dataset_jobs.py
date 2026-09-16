"""Runs the ETA/Conflict/Congestion dataset builders in a background
thread -- same rationale as `jobs.py`'s simulation `JobRegistry` and
`layout_jobs.py`'s `LayoutGenJobRegistry`: building all three datasets
from a real run set does real DB reads + parquet writes and must never
run inline in an async request handler.

Unlike layout generation, there IS a Postgres row (`model_dataset_
registry`, written by each builder itself) as the source of truth for
a *completed* export -- this registry is a purely in-memory, low-
latency cache of active/recent jobs so the dashboard can report
progress before those rows exist, mirroring `jobs.py`'s framing rather
than `layout_jobs.py`'s "disk file is truth" one.

A background thread outlives the HTTP request that started it, so it
cannot reuse `dashboard/db_session.py`'s request-scoped `db_session()`
context manager -- `start()` is handed the raw `session_factory`
callable instead, and the thread opens/closes its own session.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

MAX_CONCURRENT_JOBS = 2

# (model_name, builder_import_path) -- imported lazily inside the
# thread, same reason cli/main.py's cmd_export_dataset does: keeps
# these three modules (and their pandas/sklearn imports) out of every
# dashboard request path that never touches datasets.
_MODELS = ["eta", "conflict", "congestion"]


@dataclass
class DatasetExportJob:
    job_id: str
    status: str = "queued"  # queued | running | completed | failed
    results: dict = field(default_factory=dict)  # model_name -> {dataset_id, output_path, n_rows, n_runs}
    errors: dict = field(default_factory=dict)  # model_name -> error string


class ConcurrencyLimitError(Exception):
    pass


class DatasetExportJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, DatasetExportJob] = {}
        self._lock = threading.Lock()

    def _active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))

    def start(self, job_id: str, session_factory, run_ids: list[str], output_dir: str = "outputs/datasets") -> DatasetExportJob:
        with self._lock:
            if self._active_count() >= MAX_CONCURRENT_JOBS:
                raise ConcurrencyLimitError(
                    f"{MAX_CONCURRENT_JOBS} dataset exports already running — wait for one to finish before starting another"
                )
            job = DatasetExportJob(job_id=job_id, status="queued")
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run, args=(job, session_factory, run_ids, output_dir), daemon=True)
        thread.start()
        return job

    def _run(self, job: DatasetExportJob, session_factory, run_ids: list[str], output_dir: str) -> None:
        job.status = "running"
        session = session_factory()
        try:
            for model in _MODELS:
                try:
                    result = self._build_one(model, session, run_ids, output_dir)
                    job.results[model] = {
                        "dataset_id": result.dataset_id,
                        "output_path": result.output_path,
                        "n_rows": result.n_rows,
                        "n_runs": result.n_runs,
                    }
                except ValueError as exc:
                    # Same tolerance as cli/main.py's batch --export-datasets
                    # path: one model having no eligible data (e.g. no
                    # conflict-relevant ticks in this run set) shouldn't
                    # abort the other two.
                    session.rollback()
                    job.errors[model] = str(exc)
            job.status = "completed" if job.results else "failed"
        except Exception as exc:  # pragma: no cover - defensive, see module docstring
            job.status = "failed"
            job.errors["_job"] = str(exc)
        finally:
            session.close()

    def _build_one(self, model: str, session, run_ids: list[str], output_dir: str):
        if model == "eta":
            from fleetnet_sim.datasets.eta_builder import build_eta_dataset

            return build_eta_dataset(session, run_ids, output_dir)
        if model == "conflict":
            from fleetnet_sim.datasets.conflict_builder import build_conflict_dataset

            return build_conflict_dataset(session, run_ids, output_dir)
        from fleetnet_sim.datasets.congestion_builder import build_congestion_dataset

        return build_congestion_dataset(session, run_ids, output_dir)

    def get(self, job_id: str) -> DatasetExportJob | None:
        return self._jobs.get(job_id)
