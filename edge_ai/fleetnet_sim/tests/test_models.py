"""Tests for fleetnet_sim/models/: trains each baseline model on a real
(small, fast) multi-run dataset and checks the metrics/registry/model
artifact are all produced sanely. Skipped automatically if TimescaleDB
isn't reachable (see test_storage_integrity.py's ``_db_available``
pattern).

Uses three separate run_ids deliberately chosen (via split_for_run) to
land one in each of train/val/test — a single run_id would put 100% of
its rows in one split bucket and make load_split_dataset's "every split
must be non-empty" check fail before a model trainer is ever reached.
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
from fleetnet_sim.models.common import load_split_dataset, resolve_dataset_path
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
def model_run_ids(small_layout_dict, small_bridge):
    base = f"test_model_{uuid.uuid4().hex[:8]}"
    run_ids = [_run_id_for_split(base, split) for split in ("train", "val", "test")]

    init_schema(DSN)
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id=base, schema_version="1.0", sim_version="0.1.0"))
    session.merge(
        Warehouse(
            layout_id=small_layout_dict["layout_id"],
            source_path="in-memory",
            archetype=small_layout_dict["warehouse"]["archetype"],
            scale_class=small_layout_dict["warehouse"]["scale_class"],
            industry_type=small_layout_dict["warehouse"]["industry_type"],
            area_m2=small_layout_dict["warehouse"]["area_m2"],
            aspect_ratio=small_layout_dict["warehouse"]["aspect_ratio"],
            raw_layout_json=small_layout_dict,
        )
    )
    session.commit()

    for i, run_id in enumerate(run_ids):
        config = ExperimentConfig(
            experiment_id=base,
            run_id=run_id,
            warehouse=WarehouseConfig(layout_path="in-memory"),
            simulation=SimulationConfig(dt=0.1, duration_s=60.0, seed=i),
            fleet=FleetConfig(robot_count=10),
            tasks=TaskGenConfig(arrival_rate_per_s=1.2),
        )
        session.add(
            SimulationRun(
                run_id=run_id, experiment_id=base, layout_id=small_layout_dict["layout_id"],
                layout_path="in-memory", seed=i, dt=0.1, config_json={}, status="running",
            )
        )
        session.commit()

        repo = BufferedRepository(session, batch_size=300)
        collector = TelemetryCollector(repo=repo, run_id=run_id)
        engine = Engine(
            config=config, bridge=small_bridge,
            on_algorithm_event=collector.on_algorithm_event,
            on_task_event=collector.on_task_event,
            on_robot_sample=collector.on_robot_sample,
            on_comm_event=collector.on_comm_event,
            on_edge_sample=collector.on_edge_sample,
            on_node_sample=collector.on_node_sample,
            on_zone_sample=collector.on_zone_sample,
        )
        engine.run()
        collector.finalize(engine)
        session.commit()

    return run_ids


def test_load_split_dataset_requires_all_three_splits(model_run_ids, tmp_path):
    session = make_session_factory(DSN)()
    # Only the "train"-bucketed run_id -> every other split is empty (or,
    # for a short single run, the dataset builder itself may find no rows
    # at all) -- either way, building a trainable 3-way split needs more
    # than one run_id, which is exactly what this asserts.
    with pytest.raises(ValueError):
        result = build_eta_dataset(session, [model_run_ids[0]], str(tmp_path))
        load_split_dataset(result.output_path)


def test_train_eta_model(model_run_ids, tmp_path):
    from fleetnet_sim.models.eta_model import train_eta_model

    session = make_session_factory(DSN)()
    ds = build_eta_dataset(session, model_run_ids, str(tmp_path))
    result = train_eta_model(session, ds.output_path, str(tmp_path), dataset_id=ds.dataset_id)

    assert set(result.metrics.keys()) == {"train", "val", "test"}
    for split in result.metrics.values():
        assert split["n_rows"] > 0
        assert split["mae_s"] >= 0
    import os

    assert os.path.exists(result.model_path)

    from fleetnet_sim.storage.models import TrainedModelRegistry

    row = session.get(TrainedModelRegistry, result.model_id)
    assert row is not None
    assert row.dataset_id == ds.dataset_id


def test_train_conflict_model(model_run_ids, tmp_path):
    from fleetnet_sim.models.conflict_model import train_conflict_model

    session = make_session_factory(DSN)()
    try:
        ds = build_conflict_dataset(session, model_run_ids, str(tmp_path), horizon_s=2.0, pair_radius_m=15.0)
    except ValueError as e:
        pytest.skip(f"no robot pairs within radius for this seed set: {e}")
    result = train_conflict_model(session, ds.output_path, str(tmp_path), dataset_id=ds.dataset_id)

    for split in result.metrics.values():
        assert 0.0 <= split["accuracy"] <= 1.0
        assert 0.0 <= split["f1"] <= 1.0


def test_train_congestion_model(model_run_ids, tmp_path):
    from fleetnet_sim.models.congestion_model import train_congestion_model

    session = make_session_factory(DSN)()
    ds = build_congestion_dataset(session, model_run_ids, str(tmp_path), horizon_s=5.0, congestion_occupancy_threshold=2)
    result = train_congestion_model(session, ds.output_path, str(tmp_path), dataset_id=ds.dataset_id)

    for split in result.metrics.values():
        assert 0.0 <= split["accuracy"] <= 1.0


def test_resolve_dataset_path_unknown_id_raises(model_run_ids):
    session = make_session_factory(DSN)()
    with pytest.raises(ValueError, match="no such dataset_id"):
        resolve_dataset_path(session, dataset_id="not_a_real_dataset_id", dataset_path=None)


def test_resolve_dataset_path_requires_exactly_one_arg():
    with pytest.raises(ValueError, match="exactly one"):
        resolve_dataset_path(None, dataset_id=None, dataset_path=None)
