"""Baseline Congestion Predictor classifier, trained on
``datasets/congestion_builder.py``'s output — predicting whether an
edge's occupancy will reach the congestion threshold within the
dataset's horizon window, from its current occupancy/speed/topology
telemetry.

Feature list is imported directly from
``congestion_builder.FEATURE_COLUMNS`` (the frozen 25-feature schema)
rather than hardcoded here a second time. Booleans are cast to int for
sklearn; any missing values (e.g. an edge whose warehouse-context
lookup failed) are filled with 0 rather than dropped, so a single bad
row can't silently shrink the training set.
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.congestion_builder import FEATURE_COLUMNS
from fleetnet_sim.models.common import TrainResult, load_split_dataset, save_trained_model

LABEL_COLUMN = "label_congestion_within_horizon"
BOOL_FEATURES = ["shared_edge_flag", "shared_node_flag", "blocked_edge_flag"]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in BOOL_FEATURES:
        df[col] = df[col].astype(int)
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(0)
    return df


def _evaluate(model: RandomForestClassifier, df: pd.DataFrame) -> dict:
    X, y = df[FEATURE_COLUMNS], df[LABEL_COLUMN].astype(int)
    pred = model.predict(X)
    proba = model.predict_proba(X)[:, 1]
    metrics = {
        "n_rows": len(df),
        "positive_rate": float(y.mean()),
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
    }
    if y.nunique() > 1:
        metrics["roc_auc"] = float(roc_auc_score(y, proba))
    return metrics


def train_congestion_model(session: Session, dataset_path: str, output_dir: str, dataset_id: str | None = None) -> TrainResult:
    splits = load_split_dataset(dataset_path)
    train, val, test = _prep(splits["train"]), _prep(splits["val"]), _prep(splits["test"])

    model = RandomForestClassifier(n_estimators=200, max_depth=10, class_weight="balanced", random_state=0)
    model.fit(train[FEATURE_COLUMNS], train[LABEL_COLUMN].astype(int))

    metrics = {"train": _evaluate(model, train), "val": _evaluate(model, val), "test": _evaluate(model, test)}

    return save_trained_model(
        session,
        model=model,
        model_name="congestion",
        algorithm="RandomForestClassifier",
        feature_columns=FEATURE_COLUMNS,
        metrics=metrics,
        dataset_id=dataset_id,
        dataset_path=dataset_path,
        output_dir=output_dir,
    )
