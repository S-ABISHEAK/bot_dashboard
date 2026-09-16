"""Runs warehouse_layout's `generate_layout()` in a background thread --
same rationale as `jobs.py`'s simulation `JobRegistry`, just for layout
generation instead. Generation is CPU-bound and NOT cheap (measured
1.3-4.8s for a single "very_large" layout, and it can internally retry
up to 25 times on validation failure), so it must never run inline in
an async request handler.

`LayoutGenJobRegistry` is a purely in-memory, low-latency cache of
active generation jobs -- it does not survive a server restart. Unlike
simulation runs, there's no Postgres row to fall back on as a source of
truth here; the source of truth for a *completed* job is simply the
JSON file written to disk (picked up by `LayoutIndex` on its next
scan), and this registry only exists to report progress in the window
before that file exists.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from fleetnet_layout.generation.generator import LayoutGenerationError, generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict, write_json

MAX_CONCURRENT_JOBS = 2


@dataclass
class LayoutGenJob:
    job_id: str
    status: str = "queued"  # queued | running | completed | failed
    layout_id: str | None = None
    resolved: dict = field(default_factory=dict)
    error: dict | None = None


class ConcurrencyLimitError(Exception):
    pass


class LayoutGenJobRegistry:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self._jobs: dict[str, LayoutGenJob] = {}
        self._lock = threading.Lock()

    def _active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))

    def start(self, job_id: str, seed: int, overrides: SamplingOverrides) -> LayoutGenJob:
        with self._lock:
            if self._active_count() >= MAX_CONCURRENT_JOBS:
                raise ConcurrencyLimitError(
                    f"{MAX_CONCURRENT_JOBS} layout generations already running — wait for one to finish before starting another"
                )
            job = LayoutGenJob(job_id=job_id, status="queued")
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run, args=(job, seed, overrides), daemon=True)
        thread.start()
        return job

    def _run(self, job: LayoutGenJob, seed: int, overrides: SamplingOverrides) -> None:
        job.status = "running"
        try:
            generated = generate_layout(seed, overrides)
            data = to_json_dict(generated.config, generated.result, generated.graph, generated.metrics, generated.validation)
            self.out_dir.mkdir(parents=True, exist_ok=True)
            write_json(str(self.out_dir / f"{data['layout_id']}.json"), data)

            w = generated.config.warehouse
            job.layout_id = data["layout_id"]
            job.resolved = {
                "archetype": w.archetype.value,
                "scale_class": w.scale_class.value,
                "industry_type": w.industry_type.value,
                "dock_wall": generated.config.structural_constraints.dock_wall.value,
                "seed": seed,
                "area_m2": round(w.area_m2, 1),
                "valid": generated.validation.valid,
            }
            job.status = "completed"
        except LayoutGenerationError as exc:
            job.status = "failed"
            job.error = {"reason": exc.reason, "stage": exc.stage, "seed": exc.seed}
        except Exception as exc:  # pragma: no cover - defensive, see module docstring
            job.status = "failed"
            job.error = {"reason": str(exc), "stage": "unknown", "seed": seed}

    def get(self, job_id: str) -> LayoutGenJob | None:
        return self._jobs.get(job_id)
