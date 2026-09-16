"""Shared plumbing for the three baseline model trainers
(``eta_model.py``/``conflict_model.py``/``congestion_model.py``): dataset
loading (by parquet path or by dataset_id via ``model_dataset_registry``),
the run-level train/val/test split already baked into every dataset's
``split`` column, and persisting a trained model + its metrics with the
same traceability discipline the rest of this package uses (every
trained model is registered in ``trained_model_registry``, pointing back
at the exact dataset — and hence the exact run_ids/telemetry — that
produced it).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from fleetnet_sim.storage.models import ModelDatasetRegistry, TrainedModelRegistry


@dataclass
class TrainResult:
    model_id: str
    model_name: str
    algorithm: str
    metrics: dict
    model_path: str
    feature_columns: list[str]


def resolve_dataset_path(session: Session, *, dataset_id: str | None, dataset_path: str | None) -> tuple[str, str | None]:
    """Returns (parquet_path, dataset_id). Exactly one of dataset_id/
    dataset_path must be given; dataset_id is looked up in the registry
    so a model can always be traced back to a dataset row."""
    if dataset_id:
        row = session.get(ModelDatasetRegistry, dataset_id)
        if row is None:
            raise ValueError(f"no such dataset_id in model_dataset_registry: {dataset_id!r}")
        if row.status != "ready":
            raise ValueError(f"dataset {dataset_id!r} has status={row.status!r}, not ready")
        return row.output_path, dataset_id
    if dataset_path:
        return dataset_path, None
    raise ValueError("must supply exactly one of dataset_id or dataset_path")


def load_split_dataset(parquet_path: str) -> dict[str, pd.DataFrame]:
    df = pd.read_parquet(parquet_path)
    if "split" not in df.columns:
        raise ValueError(f"{parquet_path} has no 'split' column — was it built by a fleetnet_sim dataset builder?")
    splits = {name: df[df["split"] == name].reset_index(drop=True) for name in ("train", "val", "test")}
    for name, part in splits.items():
        if part.empty:
            raise ValueError(
                f"'{name}' split is empty ({len(df)} total rows across "
                f"{df['run_id'].nunique() if 'run_id' in df.columns else '?'} runs) — "
                "run-level splitting needs enough distinct run_ids to populate every bucket; "
                "build the dataset from more runs (see datasets/splits.py)."
            )
    return splits


def save_trained_model(
    session: Session,
    *,
    model,
    model_name: str,
    algorithm: str,
    feature_columns: list[str],
    metrics: dict,
    dataset_id: str | None,
    dataset_path: str,
    output_dir: str,
) -> TrainResult:
    model_id = f"{model_name}_model_{uuid.uuid4().hex[:12]}"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"{model_id}.joblib"
    joblib.dump(model, model_path)

    metrics_path = out_dir / f"{model_id}.metrics.json"
    metrics_path.write_text(json.dumps({"model_id": model_id, "model_name": model_name, "algorithm": algorithm, "feature_columns": feature_columns, "metrics": metrics}, indent=2))

    session.add(
        TrainedModelRegistry(
            model_id=model_id,
            model_name=model_name,
            dataset_id=dataset_id,
            dataset_path=dataset_path,
            algorithm=algorithm,
            feature_columns=feature_columns,
            metrics_json=metrics,
            model_path=str(model_path),
        )
    )
    session.commit()

    return TrainResult(model_id=model_id, model_name=model_name, algorithm=algorithm, metrics=metrics, model_path=str(model_path), feature_columns=feature_columns)
