"""Baseline Task-ETA regressor, trained on ``datasets/eta_builder.py``'s
output. Deliberately a simple, well-understood baseline (gradient-boosted
trees over the frozen ETA feature schema) — the point of this pass is
proving the full data->model loop works end to end and is honestly
evaluated on a held-out *set of runs* the model never trained on, not
squeezing out state-of-the-art accuracy.

Feature list is imported directly from ``eta_builder.FEATURE_COLUMNS``
(the frozen 21-feature schema, minus battery_voltage/payload_mass_kg —
see that module's docstring) rather than hardcoded here a second time,
so this can never silently drift out of sync with what the dataset
builder actually produces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.eta_builder import FEATURE_COLUMNS
from fleetnet_sim.models.common import TrainResult, load_split_dataset, save_trained_model

# source_zone_type/destination_zone_type are zone-type category strings
# (one-hot appropriate); everything else in the frozen schema is already
# numeric (task_type_encoded included -- a raw label encoding, not the
# same thing as one-hot on the raw task_type string, so task_type itself
# is intentionally excluded here to avoid redundant/leaking double
# encoding of the same information).
CATEGORICAL_FEATURES = ["source_zone_type", "destination_zone_type"]
NUMERIC_FEATURES = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_FEATURES]
LABEL_COLUMN = "label_remaining_time_s"


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[NUMERIC_FEATURES] = df[NUMERIC_FEATURES].fillna(0)
    df[CATEGORICAL_FEATURES] = df[CATEGORICAL_FEATURES].fillna("unknown")
    return df


def _build_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline([("pre", pre), ("model", GradientBoostingRegressor(random_state=0))])


def _evaluate(pipeline: Pipeline, df: pd.DataFrame) -> dict:
    X, y = df[FEATURE_COLUMNS], df[LABEL_COLUMN]
    pred = pipeline.predict(X)
    return {
        "n_rows": len(df),
        "mae_s": float(mean_absolute_error(y, pred)),
        "rmse_s": float(np.sqrt(mean_squared_error(y, pred))),
        "r2": float(r2_score(y, pred)),
    }


def train_eta_model(session: Session, dataset_path: str, output_dir: str, dataset_id: str | None = None) -> TrainResult:
    splits = load_split_dataset(dataset_path)
    train, val, test = _prep(splits["train"]), _prep(splits["val"]), _prep(splits["test"])
    pipeline = _build_pipeline()
    pipeline.fit(train[FEATURE_COLUMNS], train[LABEL_COLUMN])

    metrics = {
        "train": _evaluate(pipeline, train),
        "val": _evaluate(pipeline, val),
        "test": _evaluate(pipeline, test),
    }

    return save_trained_model(
        session,
        model=pipeline,
        model_name="eta",
        algorithm="GradientBoostingRegressor",
        feature_columns=FEATURE_COLUMNS,
        metrics=metrics,
        dataset_id=dataset_id,
        dataset_path=dataset_path,
        output_dir=output_dir,
    )
