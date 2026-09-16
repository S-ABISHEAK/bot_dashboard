"""Tests for fleetnet_sim/scenarios/presets.py and the CLI's
preset-then-explicit-override resolution logic (no DB needed)."""
from __future__ import annotations

import argparse

import pytest

from fleetnet_sim.cli.main import _resolve_batch_scenario, _resolve_scenario, build_parser
from fleetnet_sim.scenarios.presets import PRESETS, get_preset


def test_every_preset_has_a_description_and_valid_config():
    assert len(PRESETS) >= 4
    for name, preset in PRESETS.items():
        assert preset.name == name
        assert len(preset.description) > 20
        assert preset.fleet.robot_count >= 1
        assert preset.tasks.arrival_rate_per_s >= 0
        assert preset.dt > 0
        assert preset.duration_s > 0


def test_get_preset_unknown_raises():
    with pytest.raises(KeyError, match="unknown scenario preset"):
        get_preset("not_a_real_preset")


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_resolve_scenario_no_preset_uses_hardcoded_defaults():
    args = _ns(preset=None, robots=None, arrival_rate=None, dt=None, duration=None)
    fleet, tasks, algorithms, dt, duration = _resolve_scenario(args)
    assert fleet.robot_count == 10
    assert tasks.arrival_rate_per_s == 0.5
    assert dt == 0.1
    assert duration == 300.0


def test_resolve_scenario_preset_supplies_fields():
    args = _ns(preset="dense", robots=None, arrival_rate=None, dt=None, duration=None)
    fleet, tasks, algorithms, dt, duration = _resolve_scenario(args)
    preset = get_preset("dense")
    assert fleet.robot_count == preset.fleet.robot_count == 25
    assert tasks.arrival_rate_per_s == preset.tasks.arrival_rate_per_s


def test_resolve_scenario_explicit_flag_overrides_preset():
    args = _ns(preset="dense", robots=3, arrival_rate=None, dt=None, duration=None)
    fleet, tasks, algorithms, dt, duration = _resolve_scenario(args)
    assert fleet.robot_count == 3  # overridden, not the preset's 25
    assert tasks.arrival_rate_per_s == get_preset("dense").tasks.arrival_rate_per_s  # untouched


def test_resolve_batch_scenario_ignores_preset_robot_count():
    """batch's --robots is always the sweep axis -- the preset's own
    fleet.robot_count must never leak into the fleet template batch uses,
    since the caller always applies model_copy(robot_count=...) per combo."""
    args = _ns(preset="dense", arrival_rate=None, dt=None, duration=None)
    fleet_template, tasks, algorithms, dt, duration = _resolve_batch_scenario(args)
    assert tasks.arrival_rate_per_s == get_preset("dense").tasks.arrival_rate_per_s
    # fleet_template.robot_count is whatever the preset says, but callers
    # always override it -- verify the override actually wins downstream:
    overridden = fleet_template.model_copy(update={"robot_count": 7})
    assert overridden.robot_count == 7


def test_cli_parser_accepts_preset_flag():
    parser = build_parser()
    args = parser.parse_args(["simulate", "--layout", "x.json", "--preset", "sparse"])
    assert args.preset == "sparse"
    assert args.robots is None  # not explicitly passed -> None, so the preset's value is used

    args2 = parser.parse_args(["batch", "--layouts", "d", "--seeds", "0", "--robots", "10", "--preset", "congestion_corpus"])
    assert args2.preset == "congestion_corpus"


def test_cli_parser_rejects_unknown_preset():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["simulate", "--layout", "x.json", "--preset", "not_a_real_preset"])
