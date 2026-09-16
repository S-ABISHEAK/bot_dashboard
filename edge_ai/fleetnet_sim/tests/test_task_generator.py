"""Regression guard for TaskGenerator's picking->rack-aisle routing
(core/task_generator.py::_cells_for). Measures the mechanism directly
at the source -- calling task generation many times against a real
WorldBridge -- rather than through sparse robot_state_ts telemetry
sampling, which only incidentally catches a robot mid-pickup and gives
a tiny, misleading denominator (5 samples in one real run, versus the
1000+ direct draws here).

Parametrized over scale class and archetype: the original MEDIUM/GRID-
only fixture missed two real generator bugs --
storage.py's rows_per_block collapsing to 1 (which zeroes out secondary
aisles for a block, more likely to bite at MEDIUM/LARGE than the single
seed originally tested) and u_flow/l_flow forcing receiving+shipping
onto the same wall (which lets robots skip the aisle field entirely on
~23% of layouts, any scale). Covering LARGE/VERY_LARGE and U_FLOW/
L_FLOW here is what would have caught both.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict

from fleetnet_sim.config.schema import TaskGenConfig
from fleetnet_sim.core.task_generator import REWARD_FLOOR_FACTOR, TaskGenerator
from fleetnet_sim.integration.world_bridge import build_world_bridge

N_DRAWS = 1000

# (archetype, scale_class, seed) -- one combination per scale class the
# fix needs to hold for, plus the two archetypes that used to place
# receiving/shipping on the same wall.
LAYOUT_CASES = [
    (Archetype.GRID, ScaleClass.MEDIUM, 7),
    (Archetype.GRID, ScaleClass.LARGE, 11),
    (Archetype.GRID, ScaleClass.VERY_LARGE, 13),
    (Archetype.U_FLOW, ScaleClass.MEDIUM, 17),
    (Archetype.U_FLOW, ScaleClass.LARGE, 19),
    (Archetype.L_FLOW, ScaleClass.MEDIUM, 23),
    (Archetype.L_FLOW, ScaleClass.LARGE, 29),
]
LAYOUT_CASE_IDS = ["grid-medium", "grid-large", "grid-very_large", "u_flow-medium", "u_flow-large", "l_flow-medium", "l_flow-large"]


@pytest.fixture(scope="module", params=LAYOUT_CASES, ids=LAYOUT_CASE_IDS)
def layout_bridge(request):
    archetype, scale_class, seed = request.param
    layout = generate_layout(seed, SamplingOverrides(archetype=archetype, scale_class=scale_class))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    return build_world_bridge(data)


def test_rack_aisle_cells_populated_and_disjoint_from_picking_zone(layout_bridge):
    bridge = layout_bridge
    assert bridge.rack_aisle_cells, "expected a non-empty rack_aisle_cells pool"
    picking_zone_cells = bridge.zone_to_cells.get("picking", set())
    assert picking_zone_cells, "fixture layout should have a picking zone"
    # The two pools should be a genuinely different (and here, disjoint)
    # part of the map -- rack aisles sit in the storage field, the
    # picking zone sits in the dock-wall band.
    assert not (bridge.rack_aisle_cells & picking_zone_cells)


def test_picking_tasks_target_rack_aisle_cells_not_the_zone_band(layout_bridge):
    """The actual regression guard: every 'picking' cell TaskGenerator
    hands out must come from rack_aisle_cells (not the flat zone
    polygon) whenever that pool exists -- exercised N_DRAWS times
    directly, not inferred from a handful of lucky telemetry samples."""
    bridge = layout_bridge
    gen = TaskGenerator(bridge=bridge, config=TaskGenConfig(arrival_rate_per_s=1.0), rng=np.random.default_rng(0))

    picking_draws = 0
    in_rack_aisle = 0
    for _ in range(N_DRAWS):
        cell = gen._pick_cell("picking")
        picking_draws += 1
        if cell in bridge.rack_aisle_cells:
            in_rack_aisle += 1

    assert picking_draws == N_DRAWS
    assert in_rack_aisle == N_DRAWS, (
        f"expected 100% of {N_DRAWS} 'picking' cell draws to land in rack_aisle_cells, got {in_rack_aisle}/{N_DRAWS}"
    )


def test_make_task_end_to_end_respects_the_same_routing(layout_bridge):
    """Same guard, but through the real _make_task()/FLOW_EDGES path
    (not calling _pick_cell directly), over enough draws to collect a
    real sample of picking-sourced and picking-destined tasks."""
    bridge = layout_bridge
    gen = TaskGenerator(bridge=bridge, config=TaskGenConfig(arrival_rate_per_s=1.0), rng=np.random.default_rng(1))

    picking_pickups = 0
    picking_dropoffs = 0
    picking_pickups_in_aisle = 0
    picking_dropoffs_in_aisle = 0
    for _ in range(N_DRAWS):
        task, record = gen._make_task(sim_time=0.0)
        if record.source_zone_id == "picking":
            picking_pickups += 1
            if task.pickup in bridge.rack_aisle_cells:
                picking_pickups_in_aisle += 1
        if record.destination_zone_id == "picking":
            picking_dropoffs += 1
            if task.dropoff in bridge.rack_aisle_cells:
                picking_dropoffs_in_aisle += 1

    # FLOW_EDGES guarantees both directions occur with real weight
    # (picking->packing/returns as source, staging->picking as dest) --
    # a real denominator, not a lucky handful.
    assert picking_pickups > 50, f"too few picking-sourced tasks sampled to be meaningful: {picking_pickups}"
    assert picking_dropoffs > 50, f"too few picking-destined tasks sampled to be meaningful: {picking_dropoffs}"
    assert picking_pickups_in_aisle == picking_pickups
    assert picking_dropoffs_in_aisle == picking_dropoffs


def test_reward_floor_is_applied_and_matches_the_algebraic_bound(layout_bridge):
    """Regression guard for the CBBA task-assignment starvation bug: a
    flat reward (e.g. the 100.0 default) scores <= 0 for every agent on
    a LARGE/VERY_LARGE layout, since CBBA's try_build_bundle
    (Fleet_SIH/core/allocation/cbba.py) only accepts a task if
    score > current_best_bid (defaults to 0.0, not -inf) -- see
    task_generator.py's REWARD_FLOOR_FACTOR comment for the full
    derivation. Every generated task's reward must be at least
    2x the warehouse diagonal (the exact algebraic minimum for a
    strictly positive score to be achievable by some idle robot),
    regardless of how small config.reward is set."""
    bridge = layout_bridge
    tiny_reward = 1.0  # deliberately far below any real warehouse's diagonal
    gen = TaskGenerator(bridge=bridge, config=TaskGenConfig(arrival_rate_per_s=1.0, reward=tiny_reward), rng=np.random.default_rng(2))

    diagonal_m = math.hypot(bridge.world.width, bridge.world.height) * bridge.cell_size
    algebraic_minimum = 2.0 * diagonal_m

    for _ in range(50):
        task, _ = gen._make_task(sim_time=0.0)
        assert task.reward > algebraic_minimum, (
            f"task reward {task.reward} does not clear the algebraic minimum {algebraic_minimum} "
            f"(diagonal={diagonal_m}) -- CBBA could starve on this layout"
        )
        assert task.reward == REWARD_FLOOR_FACTOR * diagonal_m


def test_reward_floor_does_not_override_a_config_reward_that_already_clears_it():
    """Small layouts where the flat default already comfortably exceeds
    the floor must be completely unaffected -- this is a safety net for
    large-scale starvation, not a replacement for the configured
    reward."""
    layout = generate_layout(5, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    bridge = build_world_bridge(data)

    diagonal_m = math.hypot(bridge.world.width, bridge.world.height) * bridge.cell_size
    huge_reward = REWARD_FLOOR_FACTOR * diagonal_m * 100  # certainly clears the floor on a SMALL layout
    gen = TaskGenerator(bridge=bridge, config=TaskGenConfig(arrival_rate_per_s=1.0, reward=huge_reward), rng=np.random.default_rng(3))

    task, _ = gen._make_task(sim_time=0.0)
    assert task.reward == huge_reward
