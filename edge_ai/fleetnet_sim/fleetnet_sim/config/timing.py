"""Recalibrated timing constants (see plan's "Recalibration note").

``Fleet_SIH/scenarios/fleet_sim.py`` runs a fixed 60 Hz loop, so two
algorithm parameters that are conceptually *durations* are expressed
there as raw tick counts:

- ``ConflictResolver.decision_hold_ticks`` default ``60`` — a ~1.0s
  hysteresis hold (see ``core/conflict/mdpibt.py``'s docstring: "empirically
  tuned... 1.0s was found by sweeping"). Source: 60 ticks / 60 Hz = 1.0s.
- ``CBBAAgent.anti_entropy_interval`` default ``50`` — an anti-entropy
  heartbeat period. Source: 50 ticks / 60 Hz ≈ 0.8333s.

Every other tunable in fleet_sim (``STALL_THRESHOLD_S``,
``CONGESTION_TIMEOUT_S``, ``UNREACHABLE_REASSIGN_S``, ``DETOUR_COMMIT_S``,
``PICK_DROP_SECONDS``, NH-ORCA's ``TIME_HORIZON``/
``NH_ORCA_STATIC_TIME_HORIZON``) is already expressed in seconds and is
used as-is regardless of our configured ``dt`` — only tick-*counted*
parameters need conversion here.
"""
from __future__ import annotations

_FLEET_SIM_HZ = 60.0
_FLEET_SIM_DECISION_HOLD_TICKS = 60  # -> 1.0s
_FLEET_SIM_ANTI_ENTROPY_TICKS = 50  # -> 0.8333s

DECISION_HOLD_SECONDS = _FLEET_SIM_DECISION_HOLD_TICKS / _FLEET_SIM_HZ
ANTI_ENTROPY_SECONDS = _FLEET_SIM_ANTI_ENTROPY_TICKS / _FLEET_SIM_HZ

# Seconds constants carried over unchanged from fleet_sim.py (cited for
# traceability; used directly by core/robot_agent.py, not converted).
STALL_THRESHOLD_S = 1.0
RECOVERY_BURST_S = 0.4
RECOVERY_GAIN = 4.0
CONGESTION_TIMEOUT_S = 1.2
JAM_RADIUS = 1.2
JAM_SPEED_THRESH = 0.05
STALL_SPEED_THRESH = 0.05
DETOUR_COMMIT_S = 3.0
DETOUR_MAX_COST_RATIO = 1.6
UNREACHABLE_REASSIGN_S = 3.0
PICK_DROP_SECONDS = 0.6
ARRIVE_THRESH = 0.22
ADVANCE_THRESH = 0.45
NH_ORCA_TIME_HORIZON = 2.0
NH_ORCA_STATIC_TIME_HORIZON = 0.4
CONFLICT_RADIUS = 1.4
STUCK_RADIUS = 0.9


def decision_hold_ticks(dt: float) -> int:
    """Recalibrated ``ConflictResolver.decision_hold_ticks`` for a given dt."""
    return max(1, round(DECISION_HOLD_SECONDS / dt))


def anti_entropy_interval_ticks(dt: float) -> int:
    """Recalibrated ``CBBAAgent.anti_entropy_interval`` for a given dt."""
    return max(1, round(ANTI_ENTROPY_SECONDS / dt))
