"""Factory for the real ``core.conflict.mdpibt.ConflictResolver`` +
``core.conflict.karma.KarmaLedger`` — recalibrated ``decision_hold_ticks``
only (see ``config.timing``'s module docstring); every other parameter
uses fleet_sim's proven default.
"""
from __future__ import annotations

from core.conflict.karma import KarmaLedger
from core.conflict.mdpibt import ConflictResolver

from fleetnet_sim.config import timing


def make_conflict_resolver(dt: float) -> ConflictResolver:
    return ConflictResolver(
        karma=KarmaLedger(),
        conflict_radius=timing.CONFLICT_RADIUS,
        stuck_radius=timing.STUCK_RADIUS,
        decision_hold_ticks=timing.decision_hold_ticks(dt),
    )
