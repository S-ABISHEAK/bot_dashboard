"""Deterministic simulation clock (Section 4).

``simulation_time`` is derived purely from ``tick * dt`` — never from
``time.time()`` — so a run's timeline is reproducible regardless of how
fast the host machine actually executes it. ``wall_clock_time`` is kept
separately, only for real-world latency/performance reporting, and must
never feed into any decision the simulation makes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SimClock:
    dt: float = 0.1
    tick: int = 0
    _wall_start: float = field(default_factory=time.monotonic, repr=False)

    @property
    def simulation_time(self) -> float:
        return self.tick * self.dt

    @property
    def wall_clock_elapsed(self) -> float:
        return time.monotonic() - self._wall_start

    def advance(self) -> None:
        self.tick += 1
