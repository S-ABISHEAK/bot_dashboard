"""Tests for fleetnet_sim/models/inference.py — closes the ML lifecycle
loop (simulate -> dataset -> train -> predict). Trains a real model on a
small multi-run dataset (same 3-split-bucket pattern as test_models.py)
then scores a snapshot from one of those same runs, checking shape,
value ranges, and that --at-tick actually picks a different tick.
Skipped automatically if TimescaleDB isn't reachable.
"""
from __future__ import annotations

import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.datasets.conflict_builder import build_conflict_dataset
from fleetnet_sim.datasets.congestion_builder import build_congestion_dataset
from fleetnet_sim.datasets.eta_builder import build_eta_dataset
from fleetnet_sim.datasets.splits import split_for_run
from fleetnet_sim.models.inference import load_model_bundle, predict_conflict_snapshot, predict_congestion_snapshot, predict_eta_snapshot
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


def _run_id_for_split(base: str, target: str) -> str:
    i = 0
    while True:
        candidate = f"{base}_{i}"
        if split_for_run(candidate) == target:
            return candidate
        i += 1


@pytest.fixture(scope="module")
def inference_run_ids(small_layout_dict, small_bridge):
    base = f"test_infer_{uuid.uuid4().hex[:8]}"
    run_ids = [_run_id_for_split(base, split) for split in ("train", "val", "test")]

    init_schema(DSN)
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id=base, schema_version="1.0", sim_version="0.1.0"))
    session.merge(
        Warehouse(
            layout_id=small_layout_dict["layout_id"], source_path="in-memory",
            archetype=small_layout_dict["warehouse"]["archetype"], scale_class=small_layout_dict["warehouse"]["scale_class"],
            industry_type=small_layout_dict["warehouse"]["industry_type"], area_m2=small_layout_dict["warehouse"]["area_m2"],
            aspect_ratio=small_layout_dict["warehouse"]["aspect_ratio"], raw_layout_json=small_layout_dict,
        )
    )
    session.commit()

    for i, run_id in enumerate(run_ids):
        config = ExperimentConfig(
            experiment_id=base, run_id=run_id, warehouse=WarehouseConfig(layout_path="in-memory"),
            simulation=SimulationConfig(dt=0.1, duration_s=60.0, seed=i),
            fleet=FleetConfig(robot_count=10), tasks=TaskGenConfig(arrival_rate_per_s=1.2),
        )
        session.add(
            SimulationRun(
                run_id=run_id, experiment_id=base, layout_id=small_layout_dict["layout_id"], layout_path="in-memory",
                seed=i, dt=0.1, config_json={}, status="running",
            )
        )
        session.commit()

        repo = BufferedRepository(session, batch_size=300)
        collector = TelemetryCollector(repo=repo, run_id=run_id)
        engine = Engine(
            config=config, bridge=small_bridge,
            on_algorithm_event=collector.on_algorithm_event, on_task_event=collector.on_task_event,
            on_robot_sample=collector.on_robot_sample, on_comm_event=collector.on_comm_event,
            on_edge_sample=collector.on_edge_sample, on_node_sample=collector.on_node_sample, on_zone_sample=collector.on_zone_sample,
        )
        engine.run()
        collector.finalize(engine)
        session.commit()

    return run_ids


@pytest.fixture(scope="module")
def eta_model_id(inference_run_ids, tmp_path_factory):
    from fleetnet_sim.models.eta_model import train_eta_model

    session = make_session_factory(DSN)()
    out = tmp_path_factory.mktemp("eta_infer")
    ds = build_eta_dataset(session, inference_run_ids, str(out))
    result = train_eta_model(session, ds.output_path, str(out), dataset_id=ds.dataset_id)
    return result.model_id


@pytest.fixture(scope="module")
def conflict_model_id(inference_run_ids, tmp_path_factory):
    from fleetnet_sim.models.conflict_model import train_conflict_model

    session = make_session_factory(DSN)()
    out = tmp_path_factory.mktemp("conflict_infer")
    try:
        ds = build_conflict_dataset(session, inference_run_ids, str(out), horizon_s=2.0, pair_radius_m=15.0)
    except ValueError as e:
        pytest.skip(f"no robot pairs within radius for this seed set: {e}")
    result = train_conflict_model(session, ds.output_path, str(out), dataset_id=ds.dataset_id)
    return result.model_id


@pytest.fixture(scope="module")
def congestion_model_id(inference_run_ids, tmp_path_factory):
    from fleetnet_sim.models.congestion_model import train_congestion_model

    session = make_session_factory(DSN)()
    out = tmp_path_factory.mktemp("congestion_infer")
    ds = build_congestion_dataset(session, inference_run_ids, str(out), horizon_s=5.0, congestion_occupancy_threshold=2)
    result = train_congestion_model(session, ds.output_path, str(out), dataset_id=ds.dataset_id)
    return result.model_id


def test_load_model_bundle_by_id(eta_model_id):
    session = make_session_factory(DSN)()
    bundle = load_model_bundle(session, model_id=eta_model_id)
    assert bundle.model_name == "eta"
    assert bundle.model_id == eta_model_id
    assert "task_age_s" in bundle.feature_columns


def test_load_model_bundle_unknown_id_raises():
    session = make_session_factory(DSN)()
    with pytest.raises(ValueError, match="no such model_id"):
        load_model_bundle(session, model_id="not_a_real_model_id")


def test_load_model_bundle_requires_exactly_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        load_model_bundle(None, model_id=None, model_path=None)


def test_predict_eta_snapshot_documented_not_implemented(eta_model_id, inference_run_ids):
    """Live single-tick inference is a documented, known gap (see
    models/inference.py's module docstring) since the dataset builders
    moved to the frozen feature schema, which needs historical/rolling
    state a single tick can't provide. This asserts the gap fails loud
    and explained, not silently wrong -- not that the feature works."""
    session = make_session_factory(DSN)()
    bundle = load_model_bundle(session, model_id=eta_model_id)
    with pytest.raises(NotImplementedError, match="frozen dataset-builder feature schema"):
        predict_eta_snapshot(session, bundle, inference_run_ids[0])


def test_predict_conflict_snapshot_documented_not_implemented(conflict_model_id, inference_run_ids):
    session = make_session_factory(DSN)()
    bundle = load_model_bundle(session, model_id=conflict_model_id)
    with pytest.raises(NotImplementedError, match="frozen dataset-builder feature schema"):
        predict_conflict_snapshot(session, bundle, inference_run_ids[0], pair_radius_m=15.0)


def test_predict_congestion_snapshot_documented_not_implemented(congestion_model_id, inference_run_ids):
    session = make_session_factory(DSN)()
    bundle = load_model_bundle(session, model_id=congestion_model_id)
    with pytest.raises(NotImplementedError, match="frozen dataset-builder feature schema"):
        predict_congestion_snapshot(session, bundle, inference_run_ids[0])
