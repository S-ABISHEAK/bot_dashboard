"""Tests for the dashboard's layout-generation endpoints (Create Layout
tab): POST /api/layouts/generate + GET /api/layouts/generate/{job_id}/status.
Runs against a real (fast, small-scale) generation -- this exercises the
actual warehouse_layout generation pipeline, not a mock.
"""
from __future__ import annotations

import time

import pytest
from conftest import TEST_DSN
from conftest import db_available as _db_available
from fastapi.testclient import TestClient

from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.storage.db import init_schema

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


@pytest.fixture()
def client(tmp_path):
    init_schema(TEST_DSN)
    app = create_app(TEST_DSN, layouts_dirs=[str(tmp_path / "layouts")])
    return TestClient(app)


def _launch_and_wait(client, body, timeout_polls=60):
    r = client.post("/api/layouts/generate", json=body)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(timeout_polls):
        s = client.get(f"/api/layouts/generate/{job_id}/status")
        assert s.status_code == 200
        if s.json()["status"] in ("completed", "failed"):
            return s.json()
        time.sleep(0.5)
    raise TimeoutError("layout generation did not finish in time")


def test_generate_fully_random_layout(client):
    status = _launch_and_wait(client, {"scale_class": "small"})
    assert status["status"] == "completed", status
    assert status["layout_id"]
    assert status["resolved"]["scale_class"] == "small"
    # archetype/industry were left blank -- resolved must still name a real one
    assert status["resolved"]["archetype"]
    assert status["resolved"]["industry_type"]

    # the file must actually be on disk, and the layout index must pick it up
    r = client.get("/api/layouts")
    assert any(l["layout_id"] == status["layout_id"] for l in r.json()["layouts"])

    r2 = client.get(f"/api/layouts/{status['layout_id']}")
    assert r2.status_code == 200
    assert "geometry" in r2.json()


def test_generate_pinned_layout(client):
    status = _launch_and_wait(client, {"archetype": "grid", "scale_class": "small", "dock_wall": "south", "seed": 123})
    assert status["status"] == "completed", status
    assert status["resolved"]["archetype"] == "grid"
    assert status["resolved"]["scale_class"] == "small"
    assert status["resolved"]["dock_wall"] == "south"


def test_generate_invalid_archetype_422(client):
    r = client.post("/api/layouts/generate", json={"archetype": "not_a_real_archetype"})
    assert r.status_code == 422


def test_generate_invalid_dock_wall_422(client):
    r = client.post("/api/layouts/generate", json={"dock_wall": "east"})
    assert r.status_code == 422


def test_generate_status_unknown_job_404(client):
    r = client.get("/api/layouts/generate/not_a_real_job/status")
    assert r.status_code == 404
