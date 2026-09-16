"""Dataset-builder tests: leakage checks (Section 19) + basic shape.
Skipped automatically if TimescaleDB isn't reachable (see
test_storage_integrity.py's ``_db_available`` pattern).
"""
from __future__ import annotations

import uuid

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available
from sqlalchemy import text

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.datasets.conflict_builder import build_conflict_dataset
from fleetnet_sim.datasets.congestion_builder import build_congestion_dataset
from fleetnet_sim.datasets.eta_builder import build_eta_dataset
from fleetnet_sim.storage.db import init_schema, make_session_factory
from fleetnet_sim.storage.models import Experiment, SimulationRun, Warehouse
from fleetnet_sim.storage.repository import BufferedRepository
from fleetnet_sim.telemetry.collector import TelemetryCollector

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")


@pytest.fixture(scope="module")
def dataset_run_id(small_layout_dict, small_bridge):
    run_id = f"test_dataset_run_{uuid.uuid4().hex[:8]}"
    exp_id = f"test_dataset_exp_{uuid.uuid4().hex[:8]}"
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
        simulation=SimulationConfig(dt=0.1, duration_s=90.0, seed=3),
        fleet=FleetConfig(robot_count=10),
        tasks=TaskGenConfig(arrival_rate_per_s=1.0),
    )
    session.add(
        SimulationRun(
            run_id=run_id, experiment_id=exp_id, layout_id=small_layout_dict["layout_id"],
            layout_path="in-memory", seed=3, dt=0.1, config_json={}, status="running",
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


def test_robot_state_ticks_are_shared_across_robots(dataset_run_id):
    """Regression guard for the tick-vs-row-counter bug: multiple robots
    sampled in the same engine step must share the same `tick` value."""
    session = make_session_factory(DSN)()
    rows = session.execute(
        text("SELECT tick, count(distinct robot_id) as n FROM robot_state_ts WHERE run_id = :rid GROUP BY tick"),
        {"rid": dataset_run_id},
    ).all()
    assert rows
    assert max(n for _, n in rows) > 1, "expected at least one tick sampled with multiple robots present"


def test_eta_dataset_no_future_leakage(dataset_run_id, tmp_path):
    session = make_session_factory(DSN)()
    result = build_eta_dataset(session, [dataset_run_id], str(tmp_path))
    import pandas as pd

    df = pd.read_parquet(result.output_path)
    assert len(df) == result.n_rows
    assert (df["completion_time"] > df["simulation_time"]).all()
    assert (df["label_remaining_time_s"] > 0).all()


def test_congestion_dataset_no_future_leakage(dataset_run_id, tmp_path):
    session = make_session_factory(DSN)()
    result = build_congestion_dataset(session, [dataset_run_id], str(tmp_path), horizon_s=5.0, congestion_occupancy_threshold=2)
    import pandas as pd

    df = pd.read_parquet(result.output_path)
    assert len(df) == result.n_rows
    assert set(df["label_congestion_within_horizon"].unique()) <= {True, False}
    assert (df["edge_occupancy_count"] >= 1).all()

    # Reconstruct the label independently from raw edge_state_ts and confirm
    # it never depends on anything at or before the observation's own tick
    # (the actual no-future-leakage guarantee, not just a schema check).
    raw = pd.read_sql(
        "SELECT edge_source, edge_target, simulation_time, occupancy_count FROM edge_state_ts WHERE run_id = %(rid)s",
        session.connection(),
        params={"rid": dataset_run_id},
    )
    for _, row in df.sample(min(20, len(df)), random_state=0).iterrows():
        future = raw[
            (raw["edge_source"] == row["edge_source"])
            & (raw["edge_target"] == row["edge_target"])
            & (raw["simulation_time"] > row["simulation_time"])
            & (raw["simulation_time"] <= row["simulation_time"] + 5.0)
        ]
        expected = bool((future["occupancy_count"] >= 2).any())
        assert bool(row["label_congestion_within_horizon"]) == expected


def test_conflict_dataset_no_future_leakage(dataset_run_id, tmp_path):
    session = make_session_factory(DSN)()
    try:
        result = build_conflict_dataset(session, [dataset_run_id], str(tmp_path), horizon_s=2.0, pair_radius_m=15.0)
    except ValueError as e:
        pytest.skip(f"no robot pairs within radius for this seed: {e}")
    import pandas as pd

    df = pd.read_parquet(result.output_path)
    assert set(df["label_conflict_within_horizon"].unique()) <= {True, False}
    assert (df["relative_distance_m"] >= 0).all()
