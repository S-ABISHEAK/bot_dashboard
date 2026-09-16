import pytest
from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict

from fleetnet_sim.config.schema import ExperimentConfig, FleetConfig, SimulationConfig, TaskGenConfig, WarehouseConfig
from fleetnet_sim.core.engine import Engine
from fleetnet_sim.core.robot_agent import TaskState
from fleetnet_sim.integration.world_bridge import build_world_bridge


def _config(seed=1, robots=4, duration=30.0, arrival=0.5):
    return ExperimentConfig(
        experiment_id="exp_test",
        run_id=f"run_{seed}",
        warehouse=WarehouseConfig(layout_path="in-memory"),
        simulation=SimulationConfig(dt=0.1, duration_s=duration, seed=seed),
        fleet=FleetConfig(robot_count=robots),
        tasks=TaskGenConfig(arrival_rate_per_s=arrival),
    )


@pytest.fixture(scope="module")
def medium_grid_bridge():
    layout = generate_layout(7, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.MEDIUM))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    return build_world_bridge(data)


@pytest.fixture(scope="module")
def large_grid_bridge():
    layout = generate_layout(11, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.LARGE))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    return build_world_bridge(data)


def test_cbba_task_assignment_does_not_starve_on_large_layouts(large_grid_bridge):
    """Regression guard for a real, DB-confirmed bug: on a LARGE layout
    with 25 robots (arrival_rate_per_s=0.5, 400s), 187 tasks were
    created but only 8 were ever assigned (7 completed) -- 180 sat in
    'pending' forever, and 17/25 robots never moved at all. Root cause:
    Fleet_SIH's CBBA (core/allocation/cbba.py::try_build_bundle) only
    accepts a task if score > current_best_bid (default 0.0), and for
    an idle robot score = reward - (dist(robot,pickup) +
    dist(pickup,dropoff)) -- a flat reward far smaller than the
    warehouse's own diagonal (as the LARGE default is) scores <= 0 for
    every single agent, so the task is silently, permanently unwinnable
    (no exception, no algorithm_event). Fixed in task_generator.py by
    flooring reward at 2.5x the warehouse diagonal.

    This reruns the same scenario shape (same fleet size and arrival
    rate as the real failing run) and checks fleet utilization --
    fraction of robots that EVER get a task -- which is the exact
    metric the original bug was reported against ("17/25 robots never
    moved"), not the raw created-vs-assigned ratio: with a continuous
    Poisson arrival process and a per-robot capacity limit
    (FleetConfig.max_bundle=2), some queued-but-not-yet-assigned
    backlog at any single snapshot is normal, healthy queueing
    behavior, not starvation -- confirmed empirically (a lower
    assignment_rate threshold here distinguishes the fixed ~40-50%
    regime from the broken run's ~4%, while moved_fraction is the sharp
    100% vs 24% signal)."""
    task_events = []
    eng = Engine(
        config=_config(seed=1, robots=25, duration=300.0, arrival=0.5),
        bridge=large_grid_bridge,
        on_task_event=task_events.append,
    )
    eng.run()

    created = [e for e in task_events if e["event"] == "task_created"]
    assigned = [e for e in task_events if e["event"] == "task_assigned"]
    assert len(created) > 20, f"too few tasks created to be a meaningful check: {len(created)}"

    assignment_rate = len(assigned) / len(created)
    assert assignment_rate > 0.3, (
        f"only {len(assigned)}/{len(created)} ({assignment_rate:.0%}) tasks were ever assigned -- "
        "matches the broken run's ~4% rate, not the fixed run's ~45%"
    )

    ever_assigned_robots = {e["robot_id"] for e in assigned}
    moved_fraction = len(ever_assigned_robots) / len(eng.agents)
    assert moved_fraction > 0.8, (
        f"only {len(ever_assigned_robots)}/{len(eng.agents)} ({moved_fraction:.0%}) robots ever got a task -- "
        "most of the fleet sat permanently IDLE (CBBA reward-floor starvation regression)"
    )


def test_idle_robots_never_park_inside_a_rack_aisle(medium_grid_bridge):
    """Regression guard for the dashboard-observed deadlock: a robot with
    no queued task stops wherever it finished its last one
    (core/task_generator.py). Since picking pickup/dropoff cells route
    into rack_aisle_cells (often only 1-2 cells wide), an idle robot
    left parked there permanently blocks that aisle for everyone else --
    Engine._nudge_out_of_aisle is supposed to relocate it the instant it
    goes IDLE. Runs a real fleet long enough to guarantee several robots
    go idle, and checks every single IDLE sample's cell against the
    aisle pool."""
    bridge = medium_grid_bridge
    assert bridge.rack_aisle_cells, "fixture layout should have a real rack-aisle pool"

    idle_samples = []

    def on_sample(r):
        if r["task_state"] == "IDLE":
            idle_samples.append(r)

    eng = Engine(
        config=_config(duration=120.0, arrival=1.5, robots=10, seed=3),
        bridge=bridge,
        on_robot_sample=on_sample,
    )
    eng.run()

    assert len(idle_samples) > 20, f"too few IDLE samples to be a meaningful check: {len(idle_samples)}"
    stuck_in_aisle = [
        r for r in idle_samples if bridge.world_to_cell(r["x"], r["y"]) in bridge.rack_aisle_cells
    ]
    assert not stuck_in_aisle, f"{len(stuck_in_aisle)}/{len(idle_samples)} IDLE samples parked inside a rack aisle"


def test_engine_runs_without_crashing(small_bridge):
    eng = Engine(config=_config(), bridge=small_bridge)
    eng.run()
    assert eng.clock.tick == 300


def test_no_collisions_over_a_run(small_bridge):
    eng = Engine(config=_config(duration=60.0), bridge=small_bridge)
    eng.run()
    assert eng.metrics.collision_count == 0


def test_tasks_get_completed(small_bridge):
    completed = []
    eng = Engine(
        config=_config(duration=60.0, arrival=1.0),
        bridge=small_bridge,
        on_task_event=lambda e: completed.append(e) if e.get("event") == "task_completed" else None,
    )
    eng.run()
    assert len(completed) > 0


def test_same_seed_reproducible(small_bridge):
    positions_a = []
    positions_b = []
    eng_a = Engine(config=_config(seed=7, duration=20.0), bridge=small_bridge, on_robot_sample=lambda r: positions_a.append((r["robot_id"], r["x"], r["y"])))
    eng_a.run()
    eng_b = Engine(config=_config(seed=7, duration=20.0), bridge=small_bridge, on_robot_sample=lambda r: positions_b.append((r["robot_id"], r["x"], r["y"])))
    eng_b.run()
    assert positions_a == positions_b


def test_edge_node_zone_samples_emitted_and_shared_across_robots(small_bridge):
    """Occupancy aggregation should fire alongside robot_state_ts sampling
    and, with several robots, occasionally report >1 robot on the same
    edge/node/zone at once (proof the grouping is real, not per-robot)."""
    edge_samples, node_samples, zone_samples = [], [], []
    eng = Engine(
        config=_config(duration=60.0, arrival=1.0, robots=8),
        bridge=small_bridge,
        on_edge_sample=edge_samples.append,
        on_node_sample=node_samples.append,
        on_zone_sample=zone_samples.append,
    )
    eng.run()
    assert edge_samples or node_samples or zone_samples
    for ev in edge_samples:
        assert ev["occupancy_count"] >= 1
        assert ev["min_speed"] <= ev["avg_speed"] <= ev["max_speed"]
    assert any(ev["occupancy_count"] > 1 for ev in edge_samples + node_samples + zone_samples), (
        "expected at least one edge/node/zone sample with more than one robot present"
    )


def test_congestion_detour_fires_under_dense_load(small_bridge):
    """Regression guard for the ported fleet_sim._attempt_congestion_detour:
    with enough robots forced into a small layout's shared aisles, at
    least one genuine (non-gridlock-causing) detour should fire over a
    long enough run. Detour events are logged as algorithm_events with
    trigger='congestion_detour' (see engine.py::_attempt_congestion_detour).

    robots=30 (not 20): once the `grid`/`zone_based` archetypes were
    fixed to split zones onto opposite walls (see warehouse_layout's
    archetypes/grid.py) the `small` scale class layout gained a wider
    storage field between the two zone bands, so 20 robots no longer
    reliably congests it -- confirmed empirically (0/5/21 detours at
    20/30/40 robots on this exact fixture) rather than just bumped
    blindly."""
    detours = []
    eng = Engine(
        config=_config(seed=5, robots=30, duration=90.0, arrival=2.0),
        bridge=small_bridge,
        on_algorithm_event=lambda e: detours.append(e) if e.get("trigger") == "congestion_detour" else None,
    )
    eng.run()
    assert detours, "expected at least one congestion detour under dense load"
    for ev in detours:
        assert ev["output_state"]["detour_path_len"] > 0
        # DETOUR_MAX_COST_RATIO guard: a committed detour must be a real
        # alternative route, never wildly more expensive than the original.
        from fleetnet_sim.config import timing

        assert ev["output_state"]["detour_cost"] <= ev["output_state"]["original_cost"] * timing.DETOUR_MAX_COST_RATIO


def test_congestion_detour_never_routes_through_static_obstacles(small_bridge):
    """The scratch World a detour is planned on always includes every real
    static obstacle (see _attempt_congestion_detour's `scratch.obstacles =
    set(world.obstacles) | phantom_obstacles`) — a detour must never cut
    through a rack/column/exclusion cell."""
    eng = Engine(config=_config(seed=5, robots=20, duration=90.0, arrival=2.0), bridge=small_bridge)
    for _ in range(900):
        eng.step()
        for agent in eng.agents.values():
            for cell in agent.path:
                assert small_bridge.world.is_free(cell), f"detour/plan routed through blocked cell {cell}"


def test_cbba_announce_livelock_is_caught_not_fatal(small_bridge, monkeypatch):
    """Regression guard for a real, reproduced bug: Fleet_SIH's
    InProcessBus dispatches CBBA bid consensus synchronously/recursively,
    and a rare two-agent bid tie can ping-pong forever (confirmed via
    direct reproduction: robot_4/robot_5 alternating indefinitely on a
    real generated layout — raising the recursion limit to 1_000_000
    just hangs, proving it's a genuine livelock in Fleet_SIH's own
    CBBA/comms interaction, not merely deep recursion). Since we never
    modify Fleet_SIH, engine.py::_safe_announce is our circuit breaker:
    catch the RecursionError, fail only that task, keep simulating."""
    eng = Engine(config=_config(duration=5.0, arrival=5.0), bridge=small_bridge)
    # Every agent's announce_task explodes, regardless of which one CBBA's
    # own rng-driven announcer selection picks -- deterministic without
    # having to fake out the engine's shared rng (also used for Poisson
    # task-arrival thinning, which a partial rng stub would break).
    for agent in eng.agents.values():
        monkeypatch.setattr(agent.cbba, "announce_task", lambda task: (_ for _ in ()).throw(RecursionError()))

    events = []
    eng.on_algorithm_event = events.append

    # Should not raise, even though every announce attempt explodes.
    for _ in range(20):
        eng.step()

    livelock_events = [e for e in events if e.get("trigger") == "announce_livelock"]
    assert livelock_events, "expected at least one caught announce_livelock event"
    assert livelock_events[0]["success"] is False
    failed_records = [r for r in eng.task_records.values() if r.final_status == "failed_cbba_livelock"]
    assert failed_records


def test_no_motion_onto_blocked_cell(small_bridge):
    eng = Engine(config=_config(duration=40.0, arrival=1.0), bridge=small_bridge)
    for _ in range(400):
        eng.step()
        for agent in eng.agents.values():
            cell = agent.current_cell()
            assert small_bridge.world.is_free(cell), f"{agent.robot_id} standing on blocked cell {cell}"
