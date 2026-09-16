"""Tests for fleetnet_sim/dashboard/ using FastAPI's TestClient against
the isolated TEST_DSN (never the real fleetnet_sim database — see
conftest.py's module docstring on why that separation exists). Skipped
automatically if TimescaleDB isn't reachable.
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
    d = tmp_path_factory.mktemp("dashboard_layouts")
    (d / "a.json").write_text(json.dumps(small_layout_dict))
    return d


@pytest.fixture(scope="module")
def client(layouts_dir):
    init_schema(TEST_DSN)
    app = create_app(TEST_DSN, layouts_dirs=[str(layouts_dir)])
    return TestClient(app)


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "FleetNet Dashboard" in r.text


def test_list_layouts(client, small_layout_dict):
    r = client.get("/api/layouts")
    assert r.status_code == 200
    layouts = r.json()["layouts"]
    assert any(l["layout_id"] == small_layout_dict["layout_id"] for l in layouts)


def test_get_layout_full_shape(client, small_layout_dict):
    r = client.get(f"/api/layouts/{small_layout_dict['layout_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["layout_id"] == small_layout_dict["layout_id"]
    assert "geometry" in body and "navigation_graph" in body


def test_get_layout_unknown_404(client):
    r = client.get("/api/layouts/not_a_real_layout")
    assert r.status_code == 404


def test_launch_and_watch_lifecycle(client, small_layout_dict):
    r = client.post("/api/simulate", json={"layout_id": small_layout_dict["layout_id"], "robots": 5, "duration_s": 5.0, "seed": 1})
    assert r.status_code == 202
    body = r.json()
    run_id = body["run_id"]
    assert body["status"] == "started"

    # poll job status until terminal (small scenario, should be fast)
    for _ in range(60):
        s = client.get(f"/api/simulate/{run_id}/status")
        assert s.status_code == 200
        if s.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert s.json()["status"] == "completed", s.json()

    # the run must be queryable from the DB-backed endpoints too, not
    # just the in-memory job registry
    run = client.get(f"/api/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["final_tick"] is not None

    runs = client.get("/api/runs")
    assert any(r["run_id"] == run_id for r in runs.json()["runs"])

    frames = client.get(f"/api/runs/{run_id}/frames", params={"since_tick": 0, "limit": 1000})
    assert frames.status_code == 200
    fbody = frames.json()
    assert fbody["run_status"] == "completed"
    assert len(fbody["frames"]) > 0
    first = fbody["frames"][0]
    assert set(first.keys()) == {"tick", "simulation_time", "robots", "conflict_edges", "detour_robot_ids"}
    assert len(first["robots"]) > 0
    assert set(first["robots"][0].keys()) == {"robot_id", "x", "y", "yaw", "task_state", "speed"}


def test_launch_unknown_preset_returns_422(client, small_layout_dict):
    r = client.post("/api/simulate", json={"layout_id": small_layout_dict["layout_id"], "preset": "not_a_real_preset"})
    assert r.status_code == 422


def test_launch_missing_layout_returns_error(client):
    r = client.post("/api/simulate", json={"layout_id": "not_a_real_layout"})
    assert r.status_code == 404


def test_frames_unknown_run_404(client):
    r = client.get("/api/runs/not_a_real_run/frames")
    assert r.status_code == 404


def test_frames_incremental_paging_never_repeats_ticks(client, small_layout_dict):
    """Regression guard for load_frames_since: paging forward with
    since_tick=last_tick from the previous page must never return an
    already-seen tick (the exact bug class a naive re-fetch-everything
    approach would hide)."""
    r = client.post("/api/simulate", json={"layout_id": small_layout_dict["layout_id"], "robots": 5, "duration_s": 5.0, "seed": 2})
    run_id = r.json()["run_id"]
    for _ in range(60):
        if client.get(f"/api/simulate/{run_id}/status").json()["status"] == "completed":
            break
        time.sleep(0.5)

    seen_ticks = set()
    since = 0
    for _ in range(50):
        page = client.get(f"/api/runs/{run_id}/frames", params={"since_tick": since, "limit": 3}).json()
        if not page["frames"]:
            break
        ticks = [f["tick"] for f in page["frames"]]
        assert not (seen_ticks & set(ticks)), "paging returned a tick already seen on a previous page"
        seen_ticks.update(ticks)
        since = page["last_tick"]
