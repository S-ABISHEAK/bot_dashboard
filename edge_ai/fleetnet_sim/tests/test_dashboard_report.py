"""Tests for the dashboard's GET /api/runs/{run_id}/report endpoint --
the aggregated view backing the Report tab (KPI cards + timelines +
trajectories), as opposed to the plain per-run detail in
GET /api/runs/{run_id} (test_dashboard.py). Same TEST_DSN isolation
convention as the rest of the dashboard test suite.
"""
from __future__ import annotations

import json
import time

import pytest
from conftest import TEST_DSN
from conftest import db_available as _db_available
from fastapi.testclient import TestClient

from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.storage.db import init_schema

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


@pytest.fixture(scope="module")
def layouts_dir(small_layout_dict, tmp_path_factory):
    d = tmp_path_factory.mktemp("dashboard_report_layouts")
    (d / "a.json").write_text(json.dumps(small_layout_dict))
    return d


@pytest.fixture(scope="module")
def client(layouts_dir):
    init_schema(TEST_DSN)
    app = create_app(TEST_DSN, layouts_dirs=[str(layouts_dir)])
    return TestClient(app)


def _launch_and_wait(client, small_layout_dict, seed, duration_s=8.0, robots=6):
    r = client.post(
        "/api/simulate",
        json={"layout_id": small_layout_dict["layout_id"], "robots": robots, "duration_s": duration_s, "seed": seed},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    for _ in range(60):
        s = client.get(f"/api/simulate/{run_id}/status").json()
        if s["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert s["status"] == "completed", s
    return run_id


def test_report_shape(client, small_layout_dict):
    run_id = _launch_and_wait(client, small_layout_dict, seed=11)

    r = client.get(f"/api/runs/{run_id}/report")
    assert r.status_code == 200
    body = r.json()

    # same summary fields GET /runs/{id} exposes
    assert body["run_id"] == run_id
    assert body["status"] == "completed"
    assert body["metrics"] is not None

    for key in ("task_timeline", "conflict_timeline", "congestion_timeline", "replan_timeline"):
        assert key in body and isinstance(body[key], list)

    assert "trajectories" in body and isinstance(body["trajectories"], dict)
    assert len(body["trajectories"]) > 0
    for robot_id, path in body["trajectories"].items():
        assert isinstance(robot_id, str)
        assert len(path) > 0
        # capped downsampling: never more than ~150 points per robot
        assert len(path) <= 151
        for pt in path:
            assert len(pt) == 2

    # cumulative task-completion timeline must actually be non-decreasing
    cumulative = [p["cumulative"] for p in body["task_timeline"]]
    assert cumulative == sorted(cumulative)


def test_report_unknown_run_404(client):
    r = client.get("/api/runs/not_a_real_run/report")
    assert r.status_code == 404
