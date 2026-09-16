"""Baseline Conflict Predictor classifier, trained on
``datasets/conflict_builder.py``'s output — predicting whether a robot
pair enters a real (Karma/MD-PIBT-arbitrated) conflict within the
dataset's horizon window, from their current relative kinematics.

Feature list is imported directly from
``conflict_builder.FEATURE_COLUMNS`` (the frozen 24-feature schema)
rather than hardcoded here a second time. Several of those features are
booleans (cast to int for sklearn) or can be legitimately missing —
e.g. ``time_to_closest_approach_s`` when a pair isn't closing,
``eta_difference_s``/``priority_difference`` when a robot has no active
task — filled with -1 as an explicit "not applicable" sentinel (all
these features are naturally >= 0, so -1 can't be confused with a real
observation).
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sqlalchemy.orm import Session

from fleetnet_sim.datasets.conflict_builder import FEATURE_COLUMNS
from fleetnet_sim.models.common import TrainResult, load_split_dataset, save_trained_model

LABEL_COLUMN = "label_conflict_within_horizon"
BOOL_FEATURES = ["path_intersection_flag", "shared_edge_flag", "shared_node_flag"]
MISSING_SENTINEL = -1
# current_motion_state is robot A's task_state string (see conflict_builder.py's
# PROXY_FEATURE_NOTES) -- a small, fixed vocabulary, label-encoded here rather
# than one-hot for simplicity in this baseline model.
MOTION_STATE_ENCODING = {"IDLE": 0, "TO_PICKUP": 1, "PICKING": 2, "TO_DROPOFF": 3, "DROPPING": 4}


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in BOOL_FEATURES:
        df[col] = df[col].astype(int)
    df["current_motion_state"] = df["current_motion_state"].map(MOTION_STATE_ENCODING).fillna(-1)
    other_cols = [c for c in FEATURE_COLUMNS if c != "current_motion_state"]
    df[other_cols] = df[other_cols].fillna(MISSING_SENTINEL)
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


def train_conflict_model(session: Session, dataset_path: str, output_dir: str, dataset_id: str | None = None) -> TrainResult:
    splits = load_split_dataset(dataset_path)
    train, val, test = _prep(splits["train"]), _prep(splits["val"]), _prep(splits["test"])

    model = RandomForestClassifier(n_estimators=200, max_depth=10, class_weight="balanced", random_state=0)
    model.fit(train[FEATURE_COLUMNS], train[LABEL_COLUMN].astype(int))

    metrics = {"train": _evaluate(model, train), "val": _evaluate(model, val), "test": _evaluate(model, test)}

    return save_trained_model(
        session,
        model=model,
        model_name="conflict",
        algorithm="RandomForestClassifier",
        feature_columns=FEATURE_COLUMNS,
        metrics=metrics,
        dataset_id=dataset_id,
        dataset_path=dataset_path,
        output_dir=output_dir,
    )
