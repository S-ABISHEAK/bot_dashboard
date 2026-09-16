"""Fleet spawn/lifecycle (Section 3, 14).

Spawn cells are drawn from the layout's own zone entry points (staging/
charging preferred, falling back to any walkable zone cell) rather than
a hardcoded staging corridor — this is what lets the same code spawn a
fleet on any generated layout, per Section 14's "run multiple fleet
densities per layout."
"""
from __future__ import annotations

import numpy as np
from core.comms.bus import MessageBus
from core.robot import DiffDriveRobot, Pose

from fleetnet_sim.config.schema import FleetConfig
from fleetnet_sim.integration.cbba_adapter import make_cbba_agent
from fleetnet_sim.core.robot_agent import RobotAgent
from fleetnet_sim.integration.world_bridge import WorldBridge

_SPAWN_ZONE_PREFERENCE = ["staging", "charging", "receiving", "picking", "packing", "shipping", "returns", "office"]


def _spawn_cells(bridge: WorldBridge, n: int, rng: np.random.Generator) -> list:
    candidates: list = []
    for zt in _SPAWN_ZONE_PREFERENCE:
        candidates.extend(sorted(bridge.zone_to_cells.get(zt, set())))
        if len(candidates) >= n:
            break
    if len(candidates) < n:
        # Fall back to any free cell in the grid (dense fleets on small layouts).
        for x in range(bridge.world.width):
            for y in range(bridge.world.height):
                if bridge.world.is_free((x, y)):
                    candidates.append((x, y))
                if len(candidates) >= n * 4:
                    break
            if len(candidates) >= n * 4:
                break
    if not candidates:
        raise ValueError("no walkable cells available to spawn any robot")
    idx = rng.permutation(len(candidates))[: min(n, len(candidates))]
    return [candidates[i] for i in idx]


def spawn_fleet(
    bridge: WorldBridge,
    config: FleetConfig,
    bus: MessageBus,
    dt: float,
    rng: np.random.Generator,
) -> dict[str, RobotAgent]:
    cells = _spawn_cells(bridge, config.robot_count, rng)
    agents: dict[str, RobotAgent] = {}
    for i, cell in enumerate(cells):
        robot_id = f"robot_{i}"
        wx, wy = bridge.cell_to_world(*cell)
        robot = DiffDriveRobot(
            robot_id=robot_id,
            pose=Pose(x=wx, y=wy, theta=0.0),
            radius=config.robot_radius_m,
            max_speed=config.max_speed_mps,
            max_omega=config.max_omega_radps,
        )
        agent = RobotAgent(robot_id=robot_id, robot=robot, cbba=None, bridge=bridge)  # type: ignore[arg-type]
        agent.cbba = make_cbba_agent(agent, bus, dt, config.max_bundle)
        agents[robot_id] = agent
    return agents
