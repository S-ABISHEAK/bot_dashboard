"""Tests for the dashboard's dataset-export action (POST /api/datasets/
export, GET /api/datasets/export/{job_id}/status) -- the Run History
tab's "Export dataset from selected runs" button. Builds two small real
completed runs (never exported), drives the export entirely through
the HTTP API (not by calling the builders directly, unlike
test_dashboard_datasets.py), and confirms the resulting datasets show
up via the existing GET /api/datasets. Skipped automatically if
TimescaleDB isn't reachable.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available
from fastapi.testclient import TestClient

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")

POLL_TIMEOUT_S = 30
POLL_INTERVAL_S = 0.2


@pytest.fixture(scope="module")
def layouts_dir(small_layout_dict, tmp_path_factory):
    d = tmp_path_factory.mktemp("dataset_export_layouts")
    (d / "a.json").write_text(json.dumps(small_layout_dict))
    return d


@pytest.fixture(scope="module")
def client(layouts_dir):
    init_schema(DSN)
    app = create_app(DSN, layouts_dirs=[str(layouts_dir)])
    return TestClient(app)


def _make_completed_run(small_layout_dict, small_bridge, seed: int) -> str:
    run_id = f"test_dsexp_run_{uuid.uuid4().hex[:8]}"
    exp_id = f"test_dsexp_exp_{uuid.uuid4().hex[:8]}"
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
        simulation=SimulationConfig(dt=0.1, duration_s=90.0, seed=seed),
        fleet=FleetConfig(robot_count=10), tasks=TaskGenConfig(arrival_rate_per_s=1.2),
    )
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id=exp_id, layout_id=small_layout_dict["layout_id"], layout_path="in-memory",
            seed=seed, dt=0.1, config_json={}, status="running",
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
    session.query(SimulationRun).filter_by(run_id=run_id).update({"status": "completed"})
    session.commit()
    session.close()
    return run_id


@pytest.fixture(scope="module")
def two_completed_run_ids(small_layout_dict, small_bridge):
    return [
        _make_completed_run(small_layout_dict, small_bridge, seed=41),
        _make_completed_run(small_layout_dict, small_bridge, seed=42),
    ]


def _poll_until_terminal(client, job_id):
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = client.get(f"/api/datasets/export/{job_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"export job {job_id} did not reach a terminal status within {POLL_TIMEOUT_S}s")


def test_export_dataset_end_to_end(client, two_completed_run_ids):
    resp = client.post("/api/datasets/export", json={"run_ids": two_completed_run_ids})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "started"

    final = _poll_until_terminal(client, job_id)
    assert final["status"] == "completed", f"export job failed: {final}"
    assert set(final["results"].keys()) >= {"eta", "conflict", "congestion"}
    for model, result in final["results"].items():
        assert result["n_rows"] > 0, f"{model} dataset has zero rows"
        assert result["n_runs"] == 2

    listing = client.get("/api/datasets").json()["datasets"]
    dataset_ids = {d["dataset_id"] for d in listing}
    for result in final["results"].values():
        assert result["dataset_id"] in dataset_ids


def test_export_dataset_rejects_unknown_run_id(client):
    resp = client.post("/api/datasets/export", json={"run_ids": ["not_a_real_run_id"]})
    assert resp.status_code == 422


def test_export_dataset_rejects_non_completed_run(client, small_layout_dict):
    run_id = f"test_dsexp_running_{uuid.uuid4().hex[:8]}"
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id="test_dsexp_exp_running", schema_version="1.0", sim_version="0.1.0"))
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id="test_dsexp_exp_running", layout_id=small_layout_dict["layout_id"],
            layout_path="in-memory", seed=1, dt=0.1, config_json={}, status="running",
        )
    )
    session.commit()
    session.close()

    resp = client.post("/api/datasets/export", json={"run_ids": [run_id]})
    assert resp.status_code == 422


def test_export_dataset_rejects_empty_run_ids(client):
    resp = client.post("/api/datasets/export", json={"run_ids": []})
    assert resp.status_code == 422
