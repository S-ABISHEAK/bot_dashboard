"""GET /api/datasets, GET /api/datasets/{id}, GET /api/datasets/{id}/rows
-- browsing the ML datasets (ETA/Conflict/Congestion) built by
`datasets/*_builder.py`, backing the dashboard's Datasets tab.

Nothing here recomputes anything: `model_dataset_registry` (built by
every builder's own `session.add(ModelDatasetRegistry(...))` call) is
the source of truth for which datasets exist, and each export's own
`.schema.json` sidecar (same stem as its `.parquet`, written by the
builder itself) is the source of truth for its feature/label columns,
row count, and per-split/positive-rate stats -- this module only reads
and paginates, it never derives new numbers.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from fleetnet_sim.dashboard.dataset_jobs import ConcurrencyLimitError
from fleetnet_sim.dashboard.db_session import db_session
from fleetnet_sim.dashboard.schemas import ExportDatasetRequest, ExportDatasetResponse, ExportDatasetStatusResponse

router = APIRouter()

# Small in-process cache of loaded parquet files, keyed by path + mtime
# signature -- same invalidation pattern as dashboard/layout_index.py's
# LayoutIndex, so repeated pagination requests don't re-read a
# (potentially large, once batch runs land) parquet file from disk on
# every single page turn.
_PARQUET_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}


def _schema_path(output_path: str) -> Path:
    return Path(output_path).with_suffix(".schema.json")


def _load_schema(output_path: str) -> dict | None:
    path = _schema_path(output_path)
    if not path.is_file():
        return None
    with open(path) as f:
        return json.load(f)


def _load_dataframe(output_path: str) -> pd.DataFrame:
    path = Path(output_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"dataset file missing on disk: {output_path!r}")
    mtime = path.stat().st_mtime
    cached = _PARQUET_CACHE.get(output_path)
    if cached and cached[0] == mtime:
        return cached[1]
    df = pd.read_parquet(path)
    _PARQUET_CACHE[output_path] = (mtime, df)
    return df


def _registry_rows(session) -> list[dict]:
    rows = session.execute(
        text(
            "SELECT dataset_id, model_name, feature_version, created_at, source_run_ids, output_path, status "
            "FROM model_dataset_registry ORDER BY created_at DESC"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/datasets")
def list_datasets(request: Request):
    with db_session(request) as session:
        out = []
        for row in _registry_rows(session):
            schema = _load_schema(row["output_path"])
            out.append(
                {
                    "dataset_id": row["dataset_id"],
                    "model_name": row["model_name"],
                    "feature_version": row["feature_version"],
                    "created_at": row["created_at"],
                    "source_run_count": len(row["source_run_ids"] or []),
                    "status": row["status"],
                    "row_count": schema.get("row_count") if schema else None,
                    "positive_rate": schema.get("positive_rate") if schema else None,
                    "sidecar_missing": schema is None,
                }
            )
        return {"datasets": out}


def _get_registry_row(session, dataset_id: str) -> dict:
    row = session.execute(
        text(
            "SELECT dataset_id, model_name, feature_version, created_at, source_run_ids, output_path, status "
            "FROM model_dataset_registry WHERE dataset_id = :id"
        ),
        {"id": dataset_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such dataset_id: {dataset_id!r}")
    return dict(row)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    with db_session(request) as session:
        row = _get_registry_row(session, dataset_id)
    schema = _load_schema(row["output_path"])
    if schema is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id!r} is registered but its .schema.json sidecar is missing")
    return {
        **schema,
        "created_at": row["created_at"],
        "source_run_ids": row["source_run_ids"],
        "status": row["status"],
    }


@router.get("/datasets/{dataset_id}/rows")
def get_dataset_rows(dataset_id: str, request: Request, offset: int = 0, limit: int = 200, split: str | None = None):
    with db_session(request) as session:
        row = _get_registry_row(session, dataset_id)
    df = _load_dataframe(row["output_path"])

    if split:
        if "split" not in df.columns:
            raise HTTPException(status_code=422, detail="this dataset has no 'split' column to filter by")
        df = df[df["split"] == split]

    total = len(df)
    limit = max(1, min(limit, 1000))
    page = df.iloc[offset : offset + limit]
    # NaN isn't valid JSON -- pandas' to_dict keeps it as float('nan'),
    # which FastAPI's jsonable_encoder converts to `null` automatically,
    # but only if the frame doesn't have object-dtype NaNs masquerading
    # as something else; round-tripping through pandas' own NA-aware
    # `where` keeps this simple and correct for every column type here.
    records = json.loads(page.to_json(orient="records"))

    return {"rows": records, "total": total, "offset": offset, "limit": limit, "pages": math.ceil(total / limit) if limit else 0}


@router.post("/datasets/export", response_model=ExportDatasetResponse, status_code=202)
def export_dataset(body: ExportDatasetRequest, request: Request):
    """Kick off an eta+conflict+congestion dataset export for a
    user-selected set of runs (the Run History tab's "Export dataset"
    action) -- runs in the background via DatasetExportJobRegistry,
    same reasoning as layout generation's job registry: this does real
    DB reads + parquet writes and must never run inline in a request
    handler. See dataset_jobs.py's module docstring for why the
    session_factory itself (not a request-scoped db_session()) is
    passed to the job."""
    if not body.run_ids:
        raise HTTPException(status_code=422, detail="run_ids must not be empty")

    with db_session(request) as session:
        rows = session.execute(
            text("SELECT run_id, status FROM simulation_runs WHERE run_id = ANY(:ids)"),
            {"ids": body.run_ids},
        ).mappings().all()
    found = {r["run_id"]: r["status"] for r in rows}
    bad = [rid for rid in body.run_ids if found.get(rid) != "completed"]
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"these run_ids are missing or not completed, cannot export a dataset from them: {bad}",
        )

    job_id = f"dsexp_{uuid.uuid4().hex[:10]}"
    try:
        request.app.state.dataset_jobs.start(job_id, request.app.state.session_factory, body.run_ids)
    except ConcurrencyLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    return ExportDatasetResponse(job_id=job_id, status="started")


@router.get("/datasets/export/{job_id}/status", response_model=ExportDatasetStatusResponse)
def export_dataset_status(job_id: str, request: Request):
    job = request.app.state.dataset_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no tracked job for job_id: {job_id!r}")
    return ExportDatasetStatusResponse(job_id=job.job_id, status=job.status, results=job.results, errors=job.errors)
