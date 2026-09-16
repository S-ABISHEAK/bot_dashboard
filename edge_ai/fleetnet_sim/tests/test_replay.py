"""Tests for fleetnet_sim/replay/: loads a real small run's telemetry and
renders it, checking the GIF is a real multi-frame animation (not a
crash-free no-op) and that conflict/detour ticks are ever attributed to
a *sampled* tick (the nearest-tick bucketing in loader.py). Skipped
automatically if TimescaleDB isn't reachable.
"""
from __future__ import annotations

import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.replay.loader import load_replay_data
from fleetnet_sim.replay.renderer import render_replay
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


@pytest.fixture(scope="module")
def replay_run_id(small_layout_dict, small_bridge):
    run_id = f"test_replay_{uuid.uuid4().hex[:8]}"
    init_schema(DSN)
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id="test_replay_exp", schema_version="1.0", sim_version="0.1.0"))
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
    config = ExperimentConfig(
        experiment_id="test_replay_exp",
        run_id=run_id,
        warehouse=WarehouseConfig(layout_path="in-memory"),
        simulation=SimulationConfig(dt=0.1, duration_s=30.0, seed=2),
        fleet=FleetConfig(robot_count=8),
        tasks=TaskGenConfig(arrival_rate_per_s=1.5),
    )
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id="test_replay_exp", layout_id=small_layout_dict["layout_id"],
            layout_path="in-memory", seed=2, dt=0.1, config_json={}, status="running",
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
    return run_id


def test_load_replay_data_unknown_run_raises():
    session = make_session_factory(DSN)()
    with pytest.raises(ValueError, match="no such run_id"):
        load_replay_data(session, "not_a_real_run_id")


def test_load_replay_data_shapes(replay_run_id):
    session = make_session_factory(DSN)()
    data = load_replay_data(session, replay_run_id)
    assert data.ticks == sorted(data.ticks)
    assert len(data.ticks) > 1
    for tick, robots in data.robots_by_tick.items():
        assert tick in data.tick_to_time
        assert len(robots) > 0
    # every conflict/detour event got bucketed onto an actual sampled tick
    for tick in data.conflict_edges_by_tick:
        assert tick in data.ticks
    for tick in data.detour_robots_by_tick:
        assert tick in data.ticks


def test_render_replay_produces_multi_frame_gif(replay_run_id, tmp_path):
    from PIL import Image

    session = make_session_factory(DSN)()
    data = load_replay_data(session, replay_run_id)
    out_path = tmp_path / "replay.gif"
    n_frames = render_replay(data, str(out_path), fps=10, trail_length=10)

    assert n_frames == len(data.ticks)
    assert out_path.exists()
    im = Image.open(out_path)
    assert im.n_frames == n_frames
    assert im.n_frames > 1


def test_render_replay_time_window_filters_frames(replay_run_id, tmp_path):
    session = make_session_factory(DSN)()
    data = load_replay_data(session, replay_run_id)
    full_span = data.tick_to_time[data.ticks[-1]] - data.tick_to_time[data.ticks[0]]
    half_time = data.tick_to_time[data.ticks[0]] + full_span / 2

    out_path = tmp_path / "replay_windowed.gif"
    n_frames = render_replay(data, str(out_path), fps=10, end_time=half_time)
    assert 0 < n_frames < len(data.ticks)
