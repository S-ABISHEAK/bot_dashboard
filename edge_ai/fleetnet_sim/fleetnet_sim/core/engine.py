"""The simulation engine — reproduces ``fleet_sim.py``'s exact per-tick
order (see the plan's bullet list, itself quoting the real
``FleetSim._step``), generalized off Pygame/the hardcoded pod grid.

Telemetry is wired through three optional callback hooks
(``on_algorithm_event``, ``on_task_event``, ``on_robot_sample``) rather
than baked in, so Phase 1/2 can be exercised and tested with zero
storage dependency, and ``telemetry.collector.TelemetryCollector`` plugs
into the exact same hooks in Phase 3 without touching this file.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from core.avoidance.nh_orca import nh_orca_velocity
from core.conflict.mdpibt import RobotView
from core.metrics import FleetMetrics
from core.planner.dstar_lite import DStarLite
from core.world import Cell, World

from fleetnet_sim.config import timing
from fleetnet_sim.config.schema import ExperimentConfig
from fleetnet_sim.core.clock import SimClock
from fleetnet_sim.core.fleet_manager import spawn_fleet
from fleetnet_sim.core.robot_agent import RobotAgent, TaskState, dist, toward
from fleetnet_sim.core.task_generator import TaskGenerator, TaskRecord
from fleetnet_sim.integration.comms_adapter import make_bus
from fleetnet_sim.integration.conflict_adapter import make_conflict_resolver
from fleetnet_sim.integration.world_bridge import WorldBridge

EventSink = Callable[[dict], None]


def _null_sink(_event: dict) -> None:
    return None


@dataclass
class Engine:
    config: ExperimentConfig
    bridge: WorldBridge

    on_algorithm_event: EventSink = _null_sink
    on_task_event: EventSink = _null_sink
    on_robot_sample: EventSink = _null_sink
    on_comm_event: EventSink = _null_sink
    on_edge_sample: EventSink = _null_sink
    on_node_sample: EventSink = _null_sink
    on_zone_sample: EventSink = _null_sink

    clock: SimClock = field(init=False)
    rng: np.random.Generator = field(init=False)
    metrics: FleetMetrics = field(init=False)
    agents: dict[str, RobotAgent] = field(init=False, default_factory=dict)
    task_records: dict[str, TaskRecord] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.clock = SimClock(dt=self.config.simulation.dt)
        self.rng = np.random.default_rng(self.config.simulation.seed)
        self.metrics = FleetMetrics(start_tick=0)
        self.resolver = make_conflict_resolver(self.config.simulation.dt)
        self.bus = make_bus(self.config.communication, lambda: self.clock.simulation_time, self.on_comm_event)
        self.agents = spawn_fleet(self.bridge, self.config.fleet, self.bus, self.config.simulation.dt, self.rng)
        self.task_generator = TaskGenerator(bridge=self.bridge, config=self.config.tasks, rng=self.rng)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        n_ticks = int(self.config.simulation.duration_s / self.config.simulation.dt)
        for _ in range(n_ticks):
            self.step()

    def step(self) -> None:
        dt = self.config.simulation.dt
        sim_time = self.clock.simulation_time

        if self.config.algorithms.enable_cbba:
            self._maybe_spawn_task(sim_time, dt)
            for agent in self.agents.values():
                agent.cbba.step_tick()

        for agent in self.agents.values():
            self._step_task_fsm(agent, sim_time, dt)

        should_yield: dict[str, bool] = {}
        if self.config.algorithms.enable_conflict_resolver:
            views = {
                rid: RobotView(rid, a.robot.position(), a.robot.velocity_at_reference_point(0.0))
                for rid, a in self.agents.items()
                if a.state != TaskState.IDLE
            }
            if views:
                should_yield = self.resolver.resolve(views, self.clock.tick)
                self.on_algorithm_event(
                    {
                        "algorithm_name": "mdpibt_karma",
                        "trigger": "periodic",
                        "simulation_time": sim_time,
                        "tick": self.clock.tick,
                        "input_summary": {
                            "n_active_robots": len(views),
                            "positions": {rid: v.position for rid, v in views.items()},
                        },
                        # dependency_edges are (yielder, winner) pairs actively in
                        # conflict this tick — the real pairwise ground truth
                        # datasets.conflict_builder needs (Section 9.2); should_yield
                        # alone only tells you *that* a robot yielded, not *to whom*.
                        "output_state": {
                            "should_yield": should_yield,
                            "dependency_edges": list(self.resolver.dependency_edges),
                        },
                    }
                )
        for agent in self.agents.values():
            agent.should_yield = should_yield.get(agent.robot_id, False)

        neighbors = [a.robot for a in self.agents.values()]
        for agent in self.agents.values():
            self._step_motion(agent, neighbors, sim_time, dt)

        self._check_collisions()

        if self.clock.tick % self.config.telemetry.robot_state_sample_every_n_ticks == 0:
            rows = [self._robot_sample_row(agent, sim_time) for agent in self.agents.values()]
            for row in rows:
                self.on_robot_sample(dict(row))
            self._sample_occupancy(rows, sim_time)

        self.clock.advance()

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    def _safe_announce(self, announcer: RobotAgent, task, sim_time: float) -> bool:
        """Wraps ``cbba.announce_task`` against a real, observed CBBA
        failure mode: ``InProcessBus.publish`` dispatches every subscriber
        synchronously and recursively (Fleet_SIH's design, not ours — see
        README's Known Limitations), and for a rare tie in two agents'
        bids, ``_publish_bids``/``_on_bids`` can ping-pong between exactly
        two agents indefinitely rather than converging — confirmed via a
        real reproduction (robot_4/robot_5, alternating forever; raising
        Python's recursion limit to 1_000_000 just hangs instead of
        erroring, proving it's a genuine livelock, not merely deep
        recursion). This is a bug in Fleet_SIH's own CBBA/comms
        interaction, which we don't modify — this is a circuit breaker on
        our side: catch the RecursionError Python's default limit turns
        it into, log it as a real (failed) algorithm_event rather than
        hiding it, fail *only this task* (retrying the exact same
        announce would almost certainly hit the exact same deterministic
        tie again), and keep the simulation running."""
        try:
            announcer.cbba.announce_task(task)
            return True
        except RecursionError:
            self.on_algorithm_event(
                {
                    "algorithm_name": "cbba",
                    "trigger": "announce_livelock",
                    "simulation_time": sim_time,
                    "robot_id": announcer.robot_id,
                    "task_id": task.task_id,
                    "success": False,
                    "output_state": {"note": "CBBA bid consensus did not converge (RecursionError) — task abandoned, not retried"},
                }
            )
            record = self.task_records.get(task.task_id)
            if record is not None:
                record.final_status = "failed_cbba_livelock"
            return False

    def _maybe_spawn_task(self, sim_time: float, dt: float) -> None:
        active = sum(1 for r in self.task_records.values() if r.final_status in ("pending", "assigned", "in_progress"))
        result = self.task_generator.maybe_generate(sim_time, dt, active)
        if result is None:
            return
        task, record = result
        self.task_records[task.task_id] = record
        announcer = self.rng.choice(list(self.agents.values()))
        if not self._safe_announce(announcer, task, sim_time):
            return
        self.on_task_event({"event": "task_created", "task_id": task.task_id, "simulation_time": sim_time, **record.__dict__})

    def _reannounce(self, task, exclude: RobotAgent, sim_time: float) -> None:
        exclude.cbba.release_task(task.task_id)
        old_record = self.task_records.get(task.task_id)
        retry_id = f"{task.task_id}-retry{self.task_generator._next_id}"
        self.task_generator._next_id += 1
        from core.allocation.cbba import Task as CBBATask

        retry = CBBATask(task_id=retry_id, pickup=task.pickup, dropoff=task.dropoff, reward=task.reward, created_tick=self.clock.tick)
        if old_record is not None:
            new_record = TaskRecord(**{**old_record.__dict__, "task_id": retry_id})
            self.task_records[retry_id] = new_record
        candidates = [a for a in self.agents.values() if a is not exclude]
        announcer = self.rng.choice(candidates) if candidates else exclude
        if not self._safe_announce(announcer, retry, sim_time):
            return
        self.on_algorithm_event(
            {
                "algorithm_name": "cbba",
                "trigger": "reannounce",
                "simulation_time": sim_time,
                "robot_id": exclude.robot_id,
                "task_id": task.task_id,
                "output_state": {"retry_task_id": retry_id},
            }
        )

    def _nudge_out_of_aisle(self, agent: RobotAgent) -> None:
        """A robot that just went IDLE stops wherever it finished its
        last task and won't move again until CBBA hands it a new one.
        Picking pickup/dropoff cells route into WorldBridge.rack_aisle_cells
        (often only 1-2 cells / ~2m wide -- see integration/world_bridge.py),
        so an idle robot parked there can block that entire aisle for
        every other robot until it gets reassigned. Snap it to the
        nearest cell just outside the aisle instead -- a short (typically
        1-3 cell) repositioning, not a meaningful teleport, and only
        happens the instant a robot has no task to justify a real path."""
        cur = agent.current_cell()
        if cur not in self.bridge.rack_aisle_cells:
            return
        target = self.bridge.nearest_non_aisle_cell(cur)
        if target != cur:
            agent.robot.pose.x, agent.robot.pose.y = self.bridge.cell_to_world(*target)

    def _step_task_fsm(self, agent: RobotAgent, sim_time: float, dt: float) -> None:
        if agent.state == TaskState.IDLE:
            agent.robot.set_body_velocity(0.0, 0.0)
            next_task = agent.cbba.next_task() if self.config.algorithms.enable_cbba else None
            if next_task is not None:
                cur_cell = agent.current_cell()
                boxed_in = not any(agent.bridge.world.is_free(n) for n in agent.bridge.world.neighbors(cur_cell))
                if not boxed_in:
                    agent.task = next_task
                    agent.state = TaskState.TO_PICKUP
                    agent.start_route_to(agent.bridge.world, next_task.pickup)
                    record = self.task_records.get(next_task.task_id)
                    if record is not None:
                        record.assigned_robot_id = agent.robot_id
                        record.assignment_time = sim_time
                        record.final_status = "assigned"
                        record.planned_distance = agent.route_length_m()
                        self.on_task_event({"event": "task_assigned", "task_id": next_task.task_id, "simulation_time": sim_time, "robot_id": agent.robot_id})
                else:
                    self._reannounce(next_task, exclude=agent, sim_time=sim_time)
        elif agent.state in (TaskState.PICKING, TaskState.DROPPING):
            agent.robot.set_body_velocity(0.0, 0.0)
            agent.pause_timer -= dt
            if agent.pause_timer <= 0:
                if agent.state == TaskState.PICKING:
                    agent.state = TaskState.TO_DROPOFF
                    agent.start_route_to(agent.bridge.world, agent.task.dropoff)
                    record = self.task_records.get(agent.task.task_id)
                    if record is not None:
                        record.start_time = record.start_time or sim_time
                else:
                    record = self.task_records.get(agent.task.task_id)
                    if record is not None:
                        record.completion_time = sim_time
                        record.final_status = "completed"
                        record.actual_distance = agent.distance_travelled
                        record.replan_count = agent.replan_count
                        self.on_task_event({"event": "task_completed", "task_id": agent.task.task_id, "simulation_time": sim_time, "robot_id": agent.robot_id})
                        self.metrics.task_completed(sim_time - (record.assignment_time or sim_time))
                    agent.cbba.release_task(agent.task.task_id)
                    agent.task = None
                    agent.planner = None
                    agent.path = []
                    agent.distance_travelled = 0.0
                    agent.replan_count = 0
                    agent.state = TaskState.IDLE
                    self._nudge_out_of_aisle(agent)

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------
    def _nearby_static_obstacles(self, position: tuple[float, float], radius_cells: int = 3, max_count: int = 8) -> list[tuple[tuple[float, float], float]]:
        cx, cy = self.bridge.world_to_cell(*position)
        world = self.bridge.world
        found = []
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                cell = (cx + dx, cy + dy)
                if cell in world.obstacles:
                    found.append(self.bridge.cell_to_world(*cell))
        found.sort(key=lambda p: dist(p, position))
        return [(p, self.bridge.cell_size / 2.0) for p in found[:max_count]]

    def _step_motion(self, agent: RobotAgent, neighbors: list, sim_time: float, dt: float) -> None:
        detouring = sim_time < agent.detour_active_until
        did_replan = False
        if not detouring:
            did_replan = agent.refresh_plan()
        if did_replan:
            self.on_algorithm_event(
                {
                    "algorithm_name": "dstar_lite",
                    "trigger": "cell_change",
                    "simulation_time": sim_time,
                    "robot_id": agent.robot_id,
                    "output_state": {"path_len": len(agent.path), "node_expansions": agent.planner.node_expansions if agent.planner else 0},
                }
            )

        pref = (0.0, 0.0)
        prev_pos = agent.robot.position()
        if agent.state in (TaskState.TO_PICKUP, TaskState.TO_DROPOFF):
            lookahead = agent.lookahead_target()
            from core.avoidance.nh_orca import DEFAULT_EPSILON

            ref_pos = agent.robot.reference_point(DEFAULT_EPSILON)
            pref = toward(ref_pos, agent.bridge.cell_to_world(*lookahead), agent.robot.max_speed)
            if agent.should_yield:
                pref = (pref[0] * 0.05, pref[1] * 0.05)
            obstacles = self._nearby_static_obstacles(agent.robot.position()) if self.config.algorithms.enable_conflict_resolver else []
            v, w = nh_orca_velocity(
                agent.robot,
                neighbors,
                pref,
                timing.NH_ORCA_TIME_HORIZON,
                dt,
                static_obstacles=obstacles,
                static_time_horizon=timing.NH_ORCA_STATIC_TIME_HORIZON,
            )
            agent.robot.set_body_velocity(v, w)
        else:
            agent.robot.set_body_velocity(0.0, 0.0)

        agent.robot.step(dt)
        agent.distance_travelled += dist(prev_pos, agent.robot.position())

        # --- stall recovery ---
        if self.config.algorithms.enable_stall_recovery:
            v_now = agent.robot.velocity[0]
            if abs(v_now) < timing.STALL_SPEED_THRESH and not agent.should_yield:
                agent.stall_timer += dt
            else:
                agent.stall_timer = 0.0
            if agent.stall_timer > timing.STALL_THRESHOLD_S:
                agent.recovery_timer = timing.RECOVERY_BURST_S
                agent.stall_timer = 0.0
            if agent.recovery_timer > 0:
                desired_heading = math.atan2(pref[1], pref[0]) if (pref[0] or pref[1]) else agent.robot.pose.theta
                angle_diff = (desired_heading - agent.robot.pose.theta + math.pi) % (2 * math.pi) - math.pi
                recovery_omega = max(-agent.robot.max_omega, min(agent.robot.max_omega, timing.RECOVERY_GAIN * angle_diff))
                agent.robot.set_body_velocity(0.0, recovery_omega)
                agent.recovery_timer -= dt

        # --- arrival check ---
        if agent.state in (TaskState.TO_PICKUP, TaskState.TO_DROPOFF) and agent.task is not None:
            target_cell = agent.task.pickup if agent.state == TaskState.TO_PICKUP else agent.task.dropoff
            target_world = agent.bridge.cell_to_world(*target_cell)
            if dist(agent.robot.position(), target_world) < timing.ARRIVE_THRESH:
                agent.state = TaskState.PICKING if agent.state == TaskState.TO_PICKUP else TaskState.DROPPING
                agent.pause_timer = timing.PICK_DROP_SECONDS

            # --- unreachable-task reassignment ---
            if self.config.algorithms.enable_unreachable_reassignment:
                if not agent.route_reachable(target_cell):
                    agent.unreachable_timer += dt
                else:
                    agent.unreachable_timer = 0.0
                if agent.unreachable_timer >= timing.UNREACHABLE_REASSIGN_S:
                    old_task = agent.task
                    agent.task = None
                    agent.planner = None
                    agent.path = []
                    agent.unreachable_timer = 0.0
                    agent.state = TaskState.IDLE
                    self._nudge_out_of_aisle(agent)
                    self._reannounce(old_task, exclude=agent, sim_time=sim_time)

        # --- congestion detour ---
        # Ported verbatim from fleet_sim's timer/threshold logic (see
        # timing.py's JAM_SPEED_THRESH/CONGESTION_TIMEOUT_S citations).
        # Gated on `not detouring` for the same reason refresh_plan() is
        # above: a detour in progress is a one-off scratch route the live
        # D* Lite planner doesn't know about, so re-triggering detection
        # mid-detour would just immediately re-detect the jam it's still
        # driving around.
        if (
            self.config.algorithms.enable_congestion_detour
            and not detouring
            and agent.state in (TaskState.TO_PICKUP, TaskState.TO_DROPOFF)
            and agent.planner is not None
        ):
            if abs(agent.robot.velocity[0]) < timing.JAM_SPEED_THRESH:
                agent.congestion_timer += dt
            else:
                agent.congestion_timer = 0.0
            if agent.congestion_timer >= timing.CONGESTION_TIMEOUT_S:
                self._attempt_congestion_detour(agent, sim_time)
                agent.congestion_timer = 0.0

    def _path_cost(self, path: list[Cell]) -> float:
        if len(path) < 2:
            return 0.0
        total = 0.0
        for a, b in zip(path, path[1:]):
            total += dist(self.bridge.cell_to_world(*a), self.bridge.cell_to_world(*b))
        return total

    def _attempt_congestion_detour(self, agent: RobotAgent, sim_time: float) -> bool:
        """Ported verbatim from ``fleet_sim._attempt_congestion_detour``:
        treat currently-stuck nearby robots' cells, plus this robot's own
        immediate next path cells, as temporary obstacles in a *scratch*
        ``World`` and see if a real alternative route exists. Never
        touches the shared world or ``agent.planner`` (the authoritative
        D* Lite instance) — that resumes normally once
        ``detour_active_until`` elapses."""
        if agent.planner is None or not agent.path:
            return False
        cur_cell = agent.current_cell()
        goal = agent.planner.goal
        world = self.bridge.world

        phantom_obstacles: set[Cell] = set()
        for other_agent in self.agents.values():
            if other_agent is agent:
                continue
            other = other_agent.robot
            if dist(other.position(), agent.robot.position()) >= timing.JAM_RADIUS:
                continue
            if abs(other.velocity[0]) >= timing.JAM_SPEED_THRESH:
                continue  # only route around robots that are themselves stuck
            cell = self.bridge.world_to_cell(*other.position())
            if cell not in (cur_cell, goal):
                phantom_obstacles.add(cell)

        upcoming = agent.path[agent.path_index : agent.path_index + 2]
        for cell in upcoming:
            if cell not in (cur_cell, goal):
                phantom_obstacles.add(cell)

        if not phantom_obstacles:
            return False

        scratch = World(world.width, world.height, strict_diagonal_corners=True)
        scratch.obstacles = set(world.obstacles) | phantom_obstacles
        if not scratch.is_free(cur_cell) or not scratch.is_free(goal):
            return False

        detour_path = DStarLite(scratch, cur_cell, goal).get_path()
        if not detour_path or detour_path[-1] != goal:
            return False

        original_remaining = agent.path[agent.path_index :] or [cur_cell]
        original_cost = self._path_cost([cur_cell] + original_remaining)
        detour_cost = self._path_cost(detour_path)
        if detour_cost > original_cost * timing.DETOUR_MAX_COST_RATIO:
            return False

        agent.path = detour_path
        agent.path_index = 1 if len(detour_path) > 1 else 0
        agent.detour_active_until = sim_time + timing.DETOUR_COMMIT_S
        self.on_algorithm_event(
            {
                "algorithm_name": "dstar_lite",
                "trigger": "congestion_detour",
                "simulation_time": sim_time,
                "tick": self.clock.tick,
                "robot_id": agent.robot_id,
                "output_state": {
                    "phantom_obstacle_count": len(phantom_obstacles),
                    "detour_path_len": len(detour_path),
                    "original_cost": original_cost,
                    "detour_cost": detour_cost,
                },
            }
        )
        return True

    def _check_collisions(self) -> None:
        agents = list(self.agents.values())
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                d = dist(a.robot.position(), b.robot.position())
                if d < (a.robot.radius + b.robot.radius):
                    self.metrics.register_collision()

    def _robot_sample_row(self, agent: RobotAgent, sim_time: float) -> dict:
        x, y = agent.robot.position()
        cur_cell = agent.current_cell()
        return {
            "tick": self.clock.tick,
            "simulation_time": sim_time,
            "robot_id": agent.robot_id,
            "x": x,
            "y": y,
            "yaw": agent.robot.pose.theta,
            "current_node_id": self.bridge.nearest_node_id(x, y),
            "current_edge": self.bridge.nearest_edge(x, y),
            "zone_id": self.bridge.cell_to_zone.get(cur_cell),
            "task_id": agent.task.task_id if agent.task else None,
            "task_state": agent.state.name,
            "speed": agent.robot.velocity[0],
            "angular_velocity": agent.robot.velocity[1],
            "replan_count": agent.replan_count,
            "distance_travelled": agent.distance_travelled,
        }

    def _sample_occupancy(self, rows: list[dict], sim_time: float) -> None:
        """Aggregate this tick's robot samples into edge/node/zone
        occupancy — the Congestion Predictor's dependency (Section 9.1).
        Grouping key is each robot's *nearest* edge/node/zone (already
        computed per-row for ``robot_state_ts``), so this never re-derives
        position-matching logic — it just re-groups the same samples."""
        by_edge: dict[tuple[str, str], list[float]] = {}
        by_node: dict[str, list[float]] = {}
        by_zone: dict[str, list[float]] = {}
        for row in rows:
            speed = row["speed"]
            edge = row["current_edge"]
            if edge is not None:
                by_edge.setdefault(edge, []).append(speed)
            node = row["current_node_id"]
            if node is not None:
                by_node.setdefault(node, []).append(speed)
            zone = row["zone_id"]
            if zone is not None:
                by_zone.setdefault(zone, []).append(speed)

        for (u, v), speeds in by_edge.items():
            self.on_edge_sample(
                {
                    "tick": self.clock.tick,
                    "simulation_time": sim_time,
                    "edge_source": u,
                    "edge_target": v,
                    "occupancy_count": len(speeds),
                    "avg_speed": sum(speeds) / len(speeds),
                    "min_speed": min(speeds),
                    "max_speed": max(speeds),
                }
            )
        for node, speeds in by_node.items():
            self.on_node_sample(
                {
                    "tick": self.clock.tick,
                    "simulation_time": sim_time,
                    "node_id": node,
                    "occupancy_count": len(speeds),
                }
            )
        for zone, speeds in by_zone.items():
            self.on_zone_sample(
                {
                    "tick": self.clock.tick,
                    "simulation_time": sim_time,
                    "zone_type": zone,
                    "occupancy_count": len(speeds),
                    "avg_speed": sum(speeds) / len(speeds),
                }
            )
