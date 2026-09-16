"""Factory for a real ``core.allocation.cbba.CBBAAgent`` bound to one
of our robots — never a reimplementation of CBBA itself.
"""
from __future__ import annotations

from core.allocation.cbba import CBBAAgent
from core.comms.bus import MessageBus
from core.world import Cell

from fleetnet_sim.config import timing
from fleetnet_sim.core.robot_agent import RobotAgent


def make_cbba_agent(agent: RobotAgent, bus: MessageBus, dt: float, max_bundle: int) -> CBBAAgent:
    def get_position() -> Cell:
        return agent.current_cell()

    def can_participate() -> bool:
        # Mirrors fleet_sim's mobility gate: a boxed-in robot shouldn't win
        # a task it can't physically start toward.
        cell = agent.current_cell()
        return any(agent.bridge.world.is_free(n) for n in agent.bridge.world.neighbors(cell))

    return CBBAAgent(
        agent_id=agent.robot_id,
        bus=bus,
        get_position=get_position,
        max_bundle=max_bundle,
        can_participate=can_participate,
        anti_entropy_interval=timing.anti_entropy_interval_ticks(dt),
    )
