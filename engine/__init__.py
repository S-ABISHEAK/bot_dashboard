"""Decentralised multi-robot fleet simulation engine.

The five algorithm layers (A*, PIBT, RVO/ORCA, ACBBA, comms/dead-zone) live in
planner.py, coordinator.py, avoidance.py, allocator.py and comms.py and are the
*unchanged* core.  simulation.py wires them into a tick loop and produces a rich
JSON snapshot per tick for the live dashboard; render.py turns a run into MP4.
"""
from .simulation import Simulation

__all__ = ["Simulation"]
