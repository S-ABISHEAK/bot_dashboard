"""Zone-flow-based task arrival (Section 15) + the ``TaskRecord`` that
carries every telemetry field CBBA's minimal ``Task`` doesn't (Section
6). ``Task`` itself (id/pickup/dropoff/reward/created_tick) is passed to
CBBA completely unmodified — ``TaskRecord`` is a parallel record keyed
by the same ``task_id``, owned entirely by our telemetry layer.
"""
from __future__ import annotations

import math

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from core.allocation.cbba import Task
from core.world import Cell

from fleetnet_sim.config.schema import TaskGenConfig
from fleetnet_sim.integration.world_bridge import WorldBridge

# CBBA (Fleet_SIH/core/allocation/cbba.py::try_build_bundle) only accepts a
# task if score > current_best_bid, and current_best_bid defaults to 0.0
# (not -inf) -- so a task whose score is <= 0 for every single agent is
# silently, permanently unwinnable (no exception, no event). For an idle
# robot (empty route), score = reward - (dist(robot, pickup) +
# dist(pickup, dropoff)), and both distance terms are individually bounded
# by the warehouse footprint's own diagonal D. A flat reward (e.g. the
# 100.0 default) comfortably exceeds this on small/medium layouts but is
# far smaller than 2*D on LARGE/VERY_LARGE ones (diagonal ~450m at
# 100,000 m^2) -- confirmed as the root cause of a real run where 180/187
# tasks never got assigned and 17/25 robots never moved. reward > 2*D
# algebraically guarantees a strictly positive score is achievable by at
# least one idle robot for every task, regardless of scale; 2.5x gives
# headroom over the exact boundary for the strict `>` comparison and any
# route-restructuring cost on a robot with a non-empty bundle.
REWARD_FLOOR_FACTOR = 2.5

# (source_zone_type, destination_zone_type, relative_weight) — Section 15's
# standard flow, plus returns/charging as lower-weight alternates so traffic
# isn't forced through every zone uniformly.
FLOW_EDGES: list[tuple[str, str, float]] = [
    ("receiving", "staging", 3.0),
    ("staging", "picking", 3.0),
    ("picking", "packing", 3.0),
    ("packing", "shipping", 3.0),
    ("picking", "returns", 0.5),
    ("staging", "charging", 0.3),
]


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    source_zone_id: str
    destination_zone_id: str
    release_time: float
    priority: int = 1
    due_time: Optional[float] = None
    assigned_robot_id: Optional[str] = None
    assignment_time: Optional[float] = None
    planned_distance: Optional[float] = None
    actual_distance: float = 0.0
    start_time: Optional[float] = None
    completion_time: Optional[float] = None
    waiting_time: float = 0.0
    replan_count: int = 0
    final_status: str = "pending"  # pending | assigned | in_progress | completed | failed | cancelled


@dataclass
class TaskGenerator:
    bridge: WorldBridge
    config: TaskGenConfig
    rng: np.random.Generator
    _next_id: int = field(default=0)
    _reward_floor: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        diagonal_m = math.hypot(self.bridge.world.width, self.bridge.world.height) * self.bridge.cell_size
        self._reward_floor = REWARD_FLOOR_FACTOR * diagonal_m

    def maybe_generate(self, sim_time: float, dt: float, active_task_count: int) -> Optional[tuple[Task, TaskRecord]]:
        if self.config.max_active_tasks is not None and active_task_count >= self.config.max_active_tasks:
            return None
        p = self.config.arrival_rate_per_s * dt
        if self.rng.random() >= p:
            return None
        return self._make_task(sim_time)

    def _cells_for(self, zone_type: str) -> set:
        if zone_type == "picking" and self.bridge.rack_aisle_cells:
            return self.bridge.rack_aisle_cells
        return self.bridge.zone_to_cells.get(zone_type, set())

    def _pick_cell(self, zone_type: str) -> Cell:
        cells = self._cells_for(zone_type)
        if not cells:
            raise ValueError(f"zone_type {zone_type!r} has no walkable cells in this layout")
        cells_list = list(cells)
        idx = int(self.rng.integers(0, len(cells_list)))
        return cells_list[idx]

    def _make_task(self, sim_time: float) -> tuple[Task, TaskRecord]:
        weights = np.array([w for _, _, w in FLOW_EDGES], dtype=float)
        edges_available = [(s, d) for s, d, _ in FLOW_EDGES if self._cells_for(s) and self._cells_for(d)]
        if not edges_available:
            raise ValueError("no flow edge has both source and destination zones present in this layout")
        weights = weights[: len(edges_available)]
        weights = weights / weights.sum()
        idx = self.rng.choice(len(edges_available), p=weights)
        src_zone, dst_zone = edges_available[idx]

        task_id = f"task_{self._next_id}"
        self._next_id += 1

        pickup = self._pick_cell(src_zone)
        dropoff = self._pick_cell(dst_zone)

        reward = max(self.config.reward, self._reward_floor)
        task = Task(task_id=task_id, pickup=pickup, dropoff=dropoff, reward=reward, created_tick=0)
        record = TaskRecord(
            task_id=task_id,
            task_type=f"{src_zone}_to_{dst_zone}",
            source_zone_id=src_zone,
            destination_zone_id=dst_zone,
            release_time=sim_time,
        )
        return task, record
