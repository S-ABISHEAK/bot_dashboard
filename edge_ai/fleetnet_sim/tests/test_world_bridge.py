import pytest
from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict

from fleetnet_sim.integration.world_bridge import build_world_bridge


@pytest.fixture(scope="module")
def medium_grid_bridge_for_nudge():
    # small_bridge (SMALL scale) rarely has a real rack_aisle_cells pool
    # -- reuse the same MEDIUM/GRID layout pattern test_task_generator.py
    # verified always populates one.
    layout = generate_layout(7, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.MEDIUM))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    return build_world_bridge(data)


def test_bridge_builds_grid_and_zones(small_bridge):
    assert small_bridge.world.width > 0 and small_bridge.world.height > 0
    assert len(small_bridge.world.obstacles) > 0
    assert any(small_bridge.zone_to_cells.values())


def test_nearest_lookups_return_something(small_bridge):
    cx, cy = small_bridge.world.width // 2, small_bridge.world.height // 2
    x, y = small_bridge.cell_to_world(cx, cy)
    assert small_bridge.nearest_node_id(x, y) is not None
    assert small_bridge.nearest_edge(x, y) is not None


def test_nearest_free_cell_is_actually_free(small_bridge):
    # Pick a cell known to be an obstacle and confirm we get pushed off it.
    obstacle_cell = next(iter(small_bridge.world.obstacles))
    x, y = small_bridge.cell_to_world(*obstacle_cell)
    free_cell = small_bridge.nearest_free_cell(x, y)
    assert small_bridge.world.is_free(free_cell)


def test_nearest_non_aisle_cell_leaves_the_aisle(medium_grid_bridge_for_nudge):
    bridge = medium_grid_bridge_for_nudge
    assert bridge.rack_aisle_cells, "fixture layout should have a real rack-aisle pool"
    aisle_cell = next(iter(bridge.rack_aisle_cells))
    result = bridge.nearest_non_aisle_cell(aisle_cell)
    assert result not in bridge.rack_aisle_cells
    assert bridge.world.is_free(result)


def test_nearest_non_aisle_cell_is_a_noop_outside_the_aisle(medium_grid_bridge_for_nudge):
    bridge = medium_grid_bridge_for_nudge
    non_aisle_free_cell = next(
        c for c in bridge.zone_to_cells.get("staging", set()) if c not in bridge.rack_aisle_cells
    )
    assert bridge.nearest_non_aisle_cell(non_aisle_free_cell) == non_aisle_free_cell
