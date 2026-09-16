"""Section 20 integrity checks, run against a real TimescaleDB instance
(``docker compose up -d`` first). Skipped automatically if the DB isn't
reachable, so the rest of the suite stays runnable without Docker.
"""
from __future__ import annotations

import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available
from sqlalchemy import text

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.metrics.run_metrics import compute_run_metrics
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


def _run_and_persist(small_layout_dict, small_bridge, seed=1, duration=30.0, robots=5):
    run_id = f"test_run_{uuid.uuid4().hex[:8]}"
    exp_id = f"test_exp_{uuid.uuid4().hex[:8]}"
    init_schema(DSN)
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id=exp_id, schema_version="1.0", sim_version="0.1.0"))
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
        experiment_id=exp_id,
        run_id=run_id,
        warehouse=WarehouseConfig(layout_path="in-memory"),
        simulation=SimulationConfig(dt=0.1, duration_s=duration, seed=seed),
        fleet=FleetConfig(robot_count=robots),
        tasks=TaskGenConfig(arrival_rate_per_s=1.0),
    )
    session.add(
        SimulationRun(
            run_id=run_id,
            experiment_id=exp_id,
            layout_id=small_layout_dict["layout_id"],
            layout_path="in-memory",
            seed=seed,
            dt=config.simulation.dt,
            config_json={},
            status="running",
        )
    )
    session.commit()

    repo = BufferedRepository(session, batch_size=200)
    collector = TelemetryCollector(repo=repo, run_id=run_id)
    engine = Engine(
        config=config,
        bridge=small_bridge,
        on_algorithm_event=collector.on_algorithm_event,
        on_task_event=collector.on_task_event,
        on_robot_sample=collector.on_robot_sample,
        on_comm_event=collector.on_comm_event,
    )
    engine.run()
    collector.finalize(engine)

    from fleetnet_sim.storage.models import RunMetrics

    session.add(RunMetrics(run_id=run_id, metrics_json=compute_run_metrics(engine)))
    run_row = session.get(SimulationRun, run_id)
    run_row.status = "completed"
    run_row.final_tick = engine.clock.tick
    session.commit()
    return run_id, session


def test_run_persists_and_is_queryable(small_layout_dict, small_bridge):
    run_id, session = _run_and_persist(small_layout_dict, small_bridge)
    run = session.get(SimulationRun, run_id)
    assert run is not None
    assert run.status == "completed"


def test_no_orphan_algorithm_events(small_layout_dict, small_bridge):
    run_id, session = _run_and_persist(small_layout_dict, small_bridge)
    orphans = session.execute(
        text(
            "SELECT count(*) FROM algorithm_events a LEFT JOIN simulation_runs r "
            "ON a.run_id = r.run_id WHERE r.run_id IS NULL AND a.run_id = :rid"
        ),
        {"rid": run_id},
    ).scalar_one()
    assert orphans == 0


def test_communication_events_promoted_not_duplicated_in_algorithm_events(small_layout_dict, small_bridge):
    """Regression guard for the dedicated-tables promotion: communication
    events must land only in communication_events, never (also) in
    algorithm_events — see CommunicationEvent's docstring for why this
    one fully replaces the old JSONB write, unlike conflict/congestion."""
    run_id, session = _run_and_persist(small_layout_dict, small_bridge, duration=30.0, robots=5)
    comm_count = session.execute(text("SELECT count(*) FROM communication_events WHERE run_id = :rid"), {"rid": run_id}).scalar_one()
    stale_count = session.execute(
        text("SELECT count(*) FROM algorithm_events WHERE run_id = :rid AND algorithm_name = 'communication'"), {"rid": run_id}
    ).scalar_one()
    assert comm_count > 0, "expected at least one communication_events row for a run with active CBBA traffic"
    assert stale_count == 0


def test_conflict_events_mirror_dependency_edges_in_algorithm_events(small_layout_dict, small_bridge):
    """conflict_events is additive (algorithm_events still gets the raw
    mdpibt_karma audit row too) -- the promoted table's row count must
    exactly match the total dependency_edges count across those rows."""
    run_id, session = _run_and_persist(small_layout_dict, small_bridge, duration=60.0, robots=10)
    promoted_count = session.execute(text("SELECT count(*) FROM conflict_events WHERE run_id = :rid"), {"rid": run_id}).scalar_one()
    audit_rows = session.execute(
        text("SELECT output_state FROM algorithm_events WHERE run_id = :rid AND algorithm_name = 'mdpibt_karma'"), {"rid": run_id}
    ).all()
    expected = sum(len(row[0].get("dependency_edges", [])) for row in audit_rows)
    assert promoted_count == expected


def test_congestion_events_populated_under_dense_load():
    """Uses the same dense scenario test_engine.py's congestion-detour
    test relies on (known to trigger real detours) to verify the
    promoted congestion_events table actually gets populated, not just
    schema-valid-but-empty. robots=30, see test_engine.py's matching test
    for why (the grid archetype's zone-split fix widened this layout's
    storage field, so 20 robots no longer reliably congests it)."""
    from fleetnet_layout.config.enums import Archetype, ScaleClass
    from fleetnet_layout.generation.generator import generate_layout
    from fleetnet_layout.generation.sampling import SamplingOverrides
    from fleetnet_layout.serialization.json_io import to_json_dict

    from fleetnet_sim.integration.world_bridge import build_world_bridge

    layout = generate_layout(1, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    bridge = build_world_bridge(data)

    run_id = f"test_congestion_evt_{uuid.uuid4().hex[:8]}"
    exp_id = f"test_exp_{uuid.uuid4().hex[:8]}"
    init_schema(DSN)
    session = make_session_factory(DSN)()
    session.merge(Experiment(experiment_id=exp_id, schema_version="1.0", sim_version="0.1.0"))
    session.merge(
        Warehouse(
            layout_id=data["layout_id"], source_path="in-memory", archetype=data["warehouse"]["archetype"],
            scale_class=data["warehouse"]["scale_class"], industry_type=data["warehouse"]["industry_type"],
            area_m2=data["warehouse"]["area_m2"], aspect_ratio=data["warehouse"]["aspect_ratio"], raw_layout_json=data,
        )
    )
    config = ExperimentConfig(
        experiment_id=exp_id, run_id=run_id, warehouse=WarehouseConfig(layout_path="in-memory"),
        simulation=SimulationConfig(dt=0.1, duration_s=90.0, seed=5),
        fleet=FleetConfig(robot_count=30), tasks=TaskGenConfig(arrival_rate_per_s=2.0),
    )
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id=exp_id, layout_id=data["layout_id"], layout_path="in-memory",
            seed=5, dt=0.1, config_json={}, status="running",
        )
    )
    session.commit()

    repo = BufferedRepository(session, batch_size=200)
    collector = TelemetryCollector(repo=repo, run_id=run_id)
    engine = Engine(
        config=config, bridge=bridge,
        on_algorithm_event=collector.on_algorithm_event, on_task_event=collector.on_task_event,
        on_robot_sample=collector.on_robot_sample, on_comm_event=collector.on_comm_event,
    )
    engine.run()
    collector.finalize(engine)
    session.commit()

    n = session.execute(text("SELECT count(*) FROM congestion_events WHERE run_id = :rid"), {"rid": run_id}).scalar_one()
    assert n > 0, "expected at least one congestion_events row under this known-to-trigger-detours scenario"


def test_no_robot_state_on_blocked_cell(small_layout_dict, small_bridge):
    run_id, session = _run_and_persist(small_layout_dict, small_bridge)
    rows = session.execute(
        text("SELECT x, y FROM robot_state_ts WHERE run_id = :rid"), {"rid": run_id}
    ).all()
    assert rows, "expected sampled robot_state_ts rows"
    for x, y in rows:
        cell = small_bridge.world_to_cell(x, y)
        assert small_bridge.world.is_free(cell), f"robot recorded on blocked cell {cell}"


def test_completed_tasks_have_valid_lifecycle_timestamps(small_layout_dict, small_bridge):
    run_id, session = _run_and_persist(small_layout_dict, small_bridge, duration=60.0)
    rows = session.execute(
        text(
            "SELECT release_time, assignment_time, completion_time FROM tasks "
            "WHERE run_id = :rid AND final_status = 'completed'"
        ),
        {"rid": run_id},
    ).all()
    for release_time, assignment_time, completion_time in rows:
        assert release_time <= assignment_time <= completion_time


def test_reproducible_run_metrics_for_same_seed(small_layout_dict, small_bridge):
    _, session_a = _run_and_persist(small_layout_dict, small_bridge, seed=42, duration=20.0)
    _, session_b = _run_and_persist(small_layout_dict, small_bridge, seed=42, duration=20.0)
    # Metrics are computed from in-memory engine state independently of run_id,
    # so re-fetch the two most recent metrics rows for comparison.
    from fleetnet_sim.storage.models import RunMetrics

    latest = session_a.execute(text("SELECT metrics_json FROM run_metrics ORDER BY computed_at DESC LIMIT 2")).all()
    assert len(latest) == 2
    assert latest[0][0] == latest[1][0]
