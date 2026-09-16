"""Tests for the ``batch`` CLI subcommand's helpers and failure isolation."""
from __future__ import annotations

import uuid

from conftest import TEST_DSN as DSN

from fleetnet_sim.cli.main import _parse_int_list, _resolve_layouts, _run_simulation
from fleetnet_sim.config.schema import DatabaseConfig, ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig


def test_parse_int_list_ranges_and_commas():
    assert _parse_int_list("10,15,20") == [10, 15, 20]
    assert _parse_int_list("0-4") == [0, 1, 2, 3, 4]
    assert _parse_int_list("0-2,5,7-8") == [0, 1, 2, 5, 7, 8]
    assert _parse_int_list(" 3 , 1 , 2 ") == [1, 2, 3]  # de-duplicated + sorted


def test_resolve_layouts_directory(small_layout_dict, tmp_path):
    import json

    (tmp_path / "a.json").write_text(json.dumps(small_layout_dict))
    (tmp_path / "b.json").write_text(json.dumps(small_layout_dict))
    (tmp_path / "notes.txt").write_text("ignore me")
    found = _resolve_layouts(str(tmp_path))
    assert len(found) == 2
    assert all(p.endswith(".json") for p in found)


def test_resolve_layouts_comma_list():
    assert _resolve_layouts("a.json, b.json") == ["a.json", "b.json"]




def test_run_simulation_bad_layout_path_returns_failed_not_raises():
    """A batch combination with an unresolvable layout path must be caught
    and reported, never propagate and abort the rest of a batch."""
    config = ExperimentConfig(
        experiment_id="test_exp",
        run_id=f"test_run_{uuid.uuid4().hex[:8]}",
        warehouse=WarehouseConfig(layout_path="/no/such/layout.json"),
        simulation=SimulationConfig(dt=0.1, duration_s=1.0, seed=0),
        fleet=FleetConfig(robot_count=2),
        tasks=TaskGenConfig(),
        database=DatabaseConfig(dsn=DSN),
    )
    result = _run_simulation(config, skip_schema_init=True)
    assert result["status"] == "failed"
    assert "error" in result
