"""Buffered batch-insert repository (Section 13: "never silently drop
telemetry"). Rows accumulate in memory per table and are flushed in one
batch insert each; a failed flush leaves the buffer intact (raised, not
swallowed) so the caller can retry rather than losing rows.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from fleetnet_sim.storage.models import (
    AlgorithmEvent,
    CommunicationEvent,
    CongestionEvent,
    ConflictEvent,
    EdgeStateTS,
    NodeStateTS,
    Robot,
    RobotStateTS,
    RouteEvent,
    RunMetrics,
    TaskLifecycleEvent,
    TaskRow,
    ZoneStateTS,
)

_TABLE_MODELS = {
    "robots": Robot,
    "tasks": TaskRow,
    "robot_state_ts": RobotStateTS,
    "algorithm_events": AlgorithmEvent,
    "route_events": RouteEvent,
    "task_lifecycle_events": TaskLifecycleEvent,
    "run_metrics": RunMetrics,
    "edge_state_ts": EdgeStateTS,
    "node_state_ts": NodeStateTS,
    "zone_state_ts": ZoneStateTS,
    "conflict_events": ConflictEvent,
    "congestion_events": CongestionEvent,
    "communication_events": CommunicationEvent,
}


class BufferedRepository:
    def __init__(self, session: Session, batch_size: int = 500):
        self.session = session
        self.batch_size = batch_size
        self._buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(self, table: str, row: dict[str, Any]) -> None:
        if table not in _TABLE_MODELS:
            raise KeyError(f"unknown telemetry table {table!r}")
        self._buffers[table].append(row)
        if len(self._buffers[table]) >= self.batch_size:
            self.flush_table(table)

    def flush_table(self, table: str) -> int:
        rows = self._buffers.get(table)
        if not rows:
            return 0
        model = _TABLE_MODELS[table]
        n = len(rows)
        self.session.execute(insert(model), rows)
        self.session.commit()
        self._buffers[table] = []
        return n

    def flush_all(self) -> dict[str, int]:
        return {table: self.flush_table(table) for table in list(self._buffers.keys())}

    def pending_count(self, table: str) -> int:
        return len(self._buffers.get(table, []))
