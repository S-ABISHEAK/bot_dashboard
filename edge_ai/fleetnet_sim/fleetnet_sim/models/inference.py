"""Inference against a trained baseline model, closing the loop this
project's ML pipeline was built for: `simulate` -> telemetry -> dataset
-> `train-model` -> **predict**. Scores a single "snapshot" (one tick of
a stored run) rather than a rerun-time stream — a genuinely live/
streaming predictor would need the engine to call out mid-tick, which is
future work; this validates "if a trained model had been running at
tick X, what would it have said," using only telemetry that existed at
or before that tick (never anything from later, which would be the same
class of leakage the dataset builders themselves guard against).

** KNOWN GAP (documented, not silently broken) **: the three
``predict_*_snapshot`` functions below build their feature vector
inline, against the *pre-frozen-schema* feature set (a handful of
directly-observable fields at one tick). The dataset builders
(``datasets/*_builder.py``) were since extended to the frozen 25/24/21
feature schemas, most of which need historical/rolling state a single
tick alone cannot provide (``recent_*``, ``previous_*``, per-task
sequential features like ``path_turn_count``/``stop_count``/
``waiting_time_so_far_s``, etc. — see each builder's own docstring).
Making live single-tick inference produce the same feature vector as
the offline dataset builders is a real, separate task (effectively a
persistent rolling-feature-state service, not a mirror-the-builder
rewrite) — until that lands, these three functions raise
``NotImplementedError`` with this same explanation rather than silently
producing wrong/partial features. Training (``models/{eta,conflict,
congestion}_model.py``) already targets the new frozen schema and is
unaffected — only this live-snapshot path is paused.
"""
from __future__ import annotations

from dataclasses import dataclass

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from fleetnet_sim.storage.models import TrainedModelRegistry


def _feature_columns_by_model() -> dict[str, list[str]]:
    """Deferred import (rather than top-level) so importing this module
    never pulls in sklearn unless a model_path (not model_id) lookup
    actually needs it — model_id lookups get feature_columns straight
    from trained_model_registry instead."""
    from fleetnet_sim.models.conflict_model import FEATURE_COLUMNS as CONFLICT_COLUMNS
    from fleetnet_sim.models.congestion_model import FEATURE_COLUMNS as CONGESTION_COLUMNS
    from fleetnet_sim.models.eta_model import FEATURE_COLUMNS as ETA_COLUMNS

    return {"eta": ETA_COLUMNS, "conflict": CONFLICT_COLUMNS, "congestion": CONGESTION_COLUMNS}


@dataclass
class ModelBundle:
    model: object
    model_id: str | None
    model_name: str  # eta | conflict | congestion
    algorithm: str
    feature_columns: list[str]


def load_model_bundle(session: Session, *, model_id: str | None = None, model_path: str | None = None, model_name: str | None = None) -> ModelBundle:
    """Exactly one of ``model_id`` (looked up in ``trained_model_registry``,
    so a prediction can always be traced back to the model that made it)
    or ``model_path`` + ``model_name`` (the model type isn't recoverable
    from a bare .joblib file) must be given."""
    if model_id:
        row = session.get(TrainedModelRegistry, model_id)
        if row is None:
            raise ValueError(f"no such model_id in trained_model_registry: {model_id!r}")
        model = joblib.load(row.model_path)
        return ModelBundle(model=model, model_id=model_id, model_name=row.model_name, algorithm=row.algorithm, feature_columns=row.feature_columns)
    if model_path:
        if not model_name:
            raise ValueError("model_name (eta|conflict|congestion) is required alongside model_path")
        model = joblib.load(model_path)
        feature_columns = _feature_columns_by_model()[model_name]
        return ModelBundle(model=model, model_id=None, model_name=model_name, algorithm=type(model).__name__, feature_columns=feature_columns)
    raise ValueError("must supply exactly one of model_id or (model_path + model_name)")


_SNAPSHOT_GAP_MSG = (
    "live single-tick inference for {model!r} doesn't yet build the frozen dataset-builder feature "
    "schema (needs historical/rolling state a single tick can't provide -- see this module's docstring); "
    "not implemented rather than silently wrong. Use the dataset builder + a trained model against "
    "historical run data instead."
)


def predict_eta_snapshot(session: Session, bundle: ModelBundle, run_id: str, at_tick: int | None = None) -> pd.DataFrame:
    raise NotImplementedError(_SNAPSHOT_GAP_MSG.format(model="eta"))


def predict_conflict_snapshot(session: Session, bundle: ModelBundle, run_id: str, at_tick: int | None = None, pair_radius_m: float = 8.0) -> pd.DataFrame:
    raise NotImplementedError(_SNAPSHOT_GAP_MSG.format(model="conflict"))


def predict_congestion_snapshot(session: Session, bundle: ModelBundle, run_id: str, at_tick: int | None = None) -> pd.DataFrame:
    raise NotImplementedError(_SNAPSHOT_GAP_MSG.format(model="congestion"))


def predict_snapshot(session: Session, bundle: ModelBundle, run_id: str, at_tick: int | None = None, **kwargs) -> pd.DataFrame:
    if bundle.model_name == "eta":
        return predict_eta_snapshot(session, bundle, run_id, at_tick)
    if bundle.model_name == "conflict":
        return predict_conflict_snapshot(session, bundle, run_id, at_tick, pair_radius_m=kwargs.get("pair_radius_m", 8.0))
    if bundle.model_name == "congestion":
        return predict_congestion_snapshot(session, bundle, run_id, at_tick)
    raise ValueError(f"unknown model_name {bundle.model_name!r}")
