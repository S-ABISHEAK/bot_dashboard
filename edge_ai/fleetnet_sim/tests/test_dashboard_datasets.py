"""Tests for the dashboard's Datasets tab endpoints
(GET /api/datasets, /api/datasets/{id}, /api/datasets/{id}/rows).
Builds one real dataset (via the same engine-run + build_eta_dataset
pattern as test_datasets.py) against TEST_DSN, then exercises the
dashboard's read/pagination layer over it -- never the real fleetnet_sim
database. Skipped automatically if TimescaleDB isn't reachable.
"""
from __future__ import annotations

import json
import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available
from fastapi.testclient import TestClient

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.datasets.eta_builder import build_eta_dataset
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


@pytest.fixture(scope="module")
def layouts_dir(small_layout_dict, tmp_path_factory):
    d = tmp_path_factory.mktemp("dashboard_dataset_layouts")
    (d / "a.json").write_text(json.dumps(small_layout_dict))
    return d


@pytest.fixture(scope="module")
def client(layouts_dir):
    init_schema(DSN)
    app = create_app(DSN, layouts_dirs=[str(layouts_dir)])
    return TestClient(app)


@pytest.fixture(scope="module")
def eta_dataset_id(small_layout_dict, small_bridge, tmp_path_factory):
    run_id = f"test_dbds_run_{uuid.uuid4().hex[:8]}"
    exp_id = f"test_dbds_exp_{uuid.uuid4().hex[:8]}"
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id=exp_id, schema_version="1.0", sim_version="0.1.0"))
    session.merge(
        Warehouse(
            layout_id=small_layout_dict["layout_id"], source_path="in-memory",
            archetype=small_layout_dict["warehouse"]["archetype"], scale_class=small_layout_dict["warehouse"]["scale_class"],
            industry_type=small_layout_dict["warehouse"]["industry_type"], area_m2=small_layout_dict["warehouse"]["area_m2"],
            aspect_ratio=small_layout_dict["warehouse"]["aspect_ratio"], raw_layout_json=small_layout_dict,
        )
    )
    config = ExperimentConfig(
        experiment_id=exp_id, run_id=run_id, warehouse=WarehouseConfig(layout_path="in-memory"),
        simulation=SimulationConfig(dt=0.1, duration_s=90.0, seed=4),
        fleet=FleetConfig(robot_count=10), tasks=TaskGenConfig(arrival_rate_per_s=1.2),
    )
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id=exp_id, layout_id=small_layout_dict["layout_id"], layout_path="in-memory",
            seed=4, dt=0.1, config_json={}, status="running",
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

    out_dir = tmp_path_factory.mktemp("dashboard_datasets_out")
    result = build_eta_dataset(session, [run_id], str(out_dir))
    return result.dataset_id, result.n_rows


def test_list_datasets_includes_the_built_one(client, eta_dataset_id):
    dataset_id, n_rows = eta_dataset_id
    resp = client.get("/api/datasets")
    assert resp.status_code == 200
    datasets = resp.json()["datasets"]
    match = next((d for d in datasets if d["dataset_id"] == dataset_id), None)
    assert match is not None, "built dataset not found in /api/datasets listing"
    assert match["model_name"] == "eta"
    assert match["row_count"] == n_rows
    assert match["sidecar_missing"] is False


def test_get_dataset_detail_matches_schema_sidecar(client, eta_dataset_id):
    dataset_id, n_rows = eta_dataset_id
    resp = client.get(f"/api/datasets/{dataset_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_id"] == dataset_id
    assert body["row_count"] == n_rows
    assert "feature_columns" in body and len(body["feature_columns"]) == 21
    assert "dropped_from_v1" in body


def test_get_dataset_unknown_404(client):
    resp = client.get("/api/datasets/not_a_real_dataset_id")
    assert resp.status_code == 404


def test_dataset_rows_pagination_no_gaps_or_dupes(client, eta_dataset_id):
    dataset_id, n_rows = eta_dataset_id
    seen_offsets = set()
    offset = 0
    limit = 50
    total_seen = 0
    for _ in range(1000):  # safety cap, real loop bounded by `total`
        resp = client.get(f"/api/datasets/{dataset_id}/rows", params={"offset": offset, "limit": limit})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == n_rows
        if not body["rows"]:
            break
        assert offset not in seen_offsets, "same offset paginated twice"
        seen_offsets.add(offset)
        total_seen += len(body["rows"])
        offset += limit
        if offset >= body["total"]:
            break
    assert total_seen == n_rows


def test_dataset_rows_split_filter(client, eta_dataset_id):
    dataset_id, n_rows = eta_dataset_id
    # A single-run dataset deterministically hashes into exactly one of
    # train/val/test (see split_for_run) -- discover which one rather
    # than assuming "train", then confirm the filter actually filters.
    unfiltered = client.get(f"/api/datasets/{dataset_id}/rows", params={"offset": 0, "limit": 1}).json()
    actual_split = unfiltered["rows"][0]["split"]

    resp = client.get(f"/api/datasets/{dataset_id}/rows", params={"offset": 0, "limit": 10, "split": actual_split})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == n_rows  # every row belongs to this run's one split bucket
    for row in body["rows"]:
        assert row["split"] == actual_split

    other_split = next(s for s in ("train", "val", "test") if s != actual_split)
    empty = client.get(f"/api/datasets/{dataset_id}/rows", params={"offset": 0, "limit": 10, "split": other_split}).json()
    assert empty["total"] == 0


def test_dataset_rows_unknown_dataset_404(client):
    resp = client.get("/api/datasets/not_a_real_dataset_id/rows")
    assert resp.status_code == 404
