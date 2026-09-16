"""Per-robot state + task FSM + motion step.

Ported from ``Fleet_SIH/scenarios/fleet_sim.py``'s ``RobotAgent`` /
``_step_agent_task_fsm`` / ``_step_agent_motion`` (see the Explore
report quoted in the plan) — same state machine, same thresholds, same
call order — generalized off Pygame and off the hardcoded pod-grid so it
runs against any ``WorldBridge``. Every constant is imported from
``fleetnet_sim.config.timing``, which cites the exact fleet_sim source
value it was copied from; nothing here is a reinvented threshold.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from core.allocation.cbba import CBBAAgent, Task
from core.avoidance.nh_orca import nh_orca_velocity
from core.planner.dstar_lite import DStarLite
from core.robot import DiffDriveRobot
from core.world import Cell, World

from fleetnet_sim.config import timing
from fleetnet_sim.integration.world_bridge import WorldBridge


class TaskState(Enum):
    IDLE = auto()
    TO_PICKUP = auto()
    PICKING = auto()
    TO_DROPOFF = auto()
    DROPPING = auto()


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def toward(a: tuple[float, float], b: tuple[float, float], speed: float) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return (0.0, 0.0)
    return (dx / d * speed, dy / d * speed)


@dataclass
class RobotAgent:
    robot_id: str
    robot: DiffDriveRobot
    cbba: CBBAAgent
    bridge: WorldBridge

    state: TaskState = TaskState.IDLE
    task: Optional[Task] = None
    task_created_tick: int = 0

    planner: Optional[DStarLite] = None
    path: list[Cell] = field(default_factory=list)
    path_index: int = 0
    pause_timer: float = 0.0
    should_yield: bool = False

    stall_timer: float = 0.0
    recovery_timer: float = 0.0
    unreachable_timer: float = 0.0
    congestion_timer: float = 0.0
    detour_active_until: float = 0.0

    replan_count: int = 0
    last_replan_reason: str = ""
    stop_count: int = 0
    cumulative_waiting_time: float = 0.0
    is_waiting: bool = False
    waiting_start: float = 0.0
    distance_travelled: float = 0.0

    def current_cell(self) -> Cell:
        return self.bridge.world_to_cell(*self.robot.position())

    def start_route_to(self, world: World, target: Cell) -> None:
        start = self.current_cell()
        self.planner = DStarLite(world, start, target)
        self.path = self.planner.get_path()
        self.path_index = 1 if len(self.path) > 1 else 0

    def refresh_plan(self) -> bool:
        """Returns True iff a replan actually happened (cell changed)."""
        if self.planner is None:
            return False
        cur_cell = self.current_cell()
        if cur_cell != self.planner.start:
            self.planner.update_start(cur_cell)
            self.planner.compute_shortest_path()
            self.path = self.planner.get_path()
            self.path_index = 1 if len(self.path) > 1 else 0
            self.replan_count += 1
            return True
        return False

    def lookahead_target(self, advance_thresh: float = timing.ADVANCE_THRESH) -> Cell:
        if not self.path:
            return self.current_cell()
        while self.path_index < len(self.path) - 1:
            wp = self.bridge.cell_to_world(*self.path[self.path_index])
            if dist(self.robot.position(), wp) < advance_thresh:
                self.path_index += 1
            else:
                break
        return self.path[min(self.path_index, len(self.path) - 1)]

    def route_reachable(self, target_cell: Cell) -> bool:
        return bool(self.path) and self.path[-1] == target_cell

    def route_length_m(self) -> float:
        if len(self.path) < 2:
            return 0.0
        total = 0.0
        for a, b in zip(self.path, self.path[1:]):
            total += self.bridge.world.edge_cost(a, b) * self.bridge.cell_size
        return total
