"""Layer 2 + Layer 3 coordination strategies — the swappable seam of
``Simulation.step()``.

A strategy owns exactly one job: given ``active`` (the robots that should move
this tick, each with ``r.pref_next`` already set by Layer 1), decide every
robot's continuous velocity and call ``r.integrate(v, speed_cap)``.  It must
also keep the fields the rest of ``simulation.py`` / ``_snapshot()`` reads:
``r.avoiding`` / ``r.was_avoiding``, ``r.stall_ticks`` / ``r.kick_dir``,
``sim.kpi_avoided`` / ``sim.kpi_conflicts`` and
``sim._activity["pibt_pushes_tick"]``.

* ``StackStrategy``    — the real 5-layer stack: MD-PIBT next-cell + NH-ORCA
                         velocity + the ORCA-freeze lateral-kick workaround.
* ``StopWaitStrategy`` — a *realistic* decentralised baseline: single-cell
                         reservation (stop and wait when the next cell is
                         taken), plus the two recovery mechanisms real AGV
                         stop-and-wait systems use — timeout-triggered priority
                         override (a long-waiting robot jumps the queue for a
                         contested cell) and a reactive D* Lite detour around a
                         robot that is permanently blocking it.  What it still
                         lacks vs. the stack: proactive coordination (PIBT
                         priority inheritance, NH-ORCA).  The recovery is not
                         free — every detour's extra distance is tracked.
"""
import numpy as np

from . import config as C
from .avoidance import choose_velocity
from .planner import astar


def _c(cell):
    return np.array([cell[0] + 0.5, cell[1] + 0.5], float)


class CoordinationStrategy:
    name = "base"

    def move(self, sim, active):
        raise NotImplementedError


class StackStrategy(CoordinationStrategy):
    """MD-PIBT (Layer 2) + NH-ORCA (Layer 3), verbatim from the original
    ``Simulation.step()`` body."""
    name = "stack"

    def move(self, sim, active):
        # 5. Layer 2: PIBT
        order = [sim.robots[i] for i in sim.priority_order
                 if sim.robots[i] in active]
        active_set = set(active)
        reserved = {r.cell for r in sim.robots
                    if not r.alive or r.phase == "charging"
                    or (r.task is None and r not in active_set)}
        dist_fields = {r.id: sim._distance_field(r.goal_cell) for r in active}
        next_cells = sim.pibt.step(order, dist_fields, sim.congestion, reserved)
        for r in active:
            if next_cells.get(r.id) not in (r.cell, r.pref_next):
                sim._activity["pibt_pushes_tick"] += 1

        # 6. Layer 3: reciprocal avoidance + integrate
        for r in active:
            target = next_cells.get(r.id, r.cell)
            speed_cap = C.MAX_SPEED if r.connected else C.CAUTION_SPEED
            to_t = _c(target) - r.pos
            d = np.linalg.norm(to_t)
            pref_v = (to_t / d * speed_cap) if d > 1e-6 else np.zeros(2)
            if r.kick_dir is not None:
                pref_v = pref_v + r.kick_dir * C.STANDOFF_KICK

            neigh, _conn = sim.comms.neighbours_for(r)
            if not r.connected:
                neigh = [(o.pos.copy(), o.vel.copy()) for o in sim.robots
                         if o.id != r.id and o.alive
                         and np.linalg.norm(o.pos - r.pos) <= C.SENSE_RADIUS]

            assertive = r.stall_ticks > C.STANDOFF_TICKS
            statics = [] if assertive else sim._static_cells_near(r.pos)
            v = choose_velocity(r.pos, r.vel, pref_v, speed_cap, neigh, statics)
            if assertive and np.linalg.norm(v) < 0.3 and d > 1e-6:
                v = to_t / d * speed_cap * 0.9
            r.integrate(v, speed_cap)

            r.was_avoiding = r.avoiding
            r.avoiding = float(np.linalg.norm(v - pref_v)) > 0.18
            if r.avoiding and not r.was_avoiding:
                sim.kpi_avoided += 1

            if np.linalg.norm(r.vel) < 0.12 and d > 0.55:
                r.stall_ticks += 1
            else:
                r.stall_ticks = max(0, r.stall_ticks - 2)
                if r.stall_ticks == 0:
                    r.kick_dir = None
            if r.stall_ticks > C.STANDOFF_TICKS and r.kick_dir is None:
                perp = np.array([-pref_v[1], pref_v[0]])
                nn = np.linalg.norm(perp)
                r.kick_dir = (perp / nn if nn > 1e-6 else np.array([0.0, 1.0]))
                r.kick_dir *= (1 if r.id % 2 == 0 else -1)
                sim.kpi_conflicts += 1


class StopWaitStrategy(CoordinationStrategy):
    """Realistic stop-and-wait baseline: single-cell reservation + timeout
    recovery (priority override + reactive D* Lite detour)."""
    name = "stopwait"

    def __init__(self):
        self._wait_streak = {}             # robot.id -> consecutive ticks waited

    def _drive(self, r, tgt, speed_cap):
        to_t = _c(tgt) - r.pos
        d = np.linalg.norm(to_t)
        v = (to_t / d * min(speed_cap, d / C.DT)) if d > 0.02 else np.zeros(2)
        r.integrate(v, speed_cap)

    @staticmethod
    def _housekeep(r):
        r.was_avoiding = r.avoiding
        r.avoiding = False
        r.kick_dir = None

    def move(self, sim, active):
        active_ids = {r.id for r in active}
        for rid in list(self._wait_streak):
            if rid not in active_ids:
                self._wait_streak.pop(rid, None)

        base = [sim.robots[i] for i in sim.priority_order
                if sim.robots[i].id in active_ids]
        seen = {r.id for r in base}
        base += [r for r in active if r.id not in seen]

        # (1) timeout-triggered priority override: robots that have been waiting
        #     past the threshold jump to the front, most-stuck first, so they
        #     win the next contested cell instead of losing it again.
        over = sorted((r for r in base
                       if self._wait_streak.get(r.id, 0) > C.SW_OVERRIDE_TICKS),
                      key=lambda r: -self._wait_streak[r.id])
        over_ids = {r.id for r in over}
        ordered = over + [r for r in base if r.id not in over_ids]

        # a robot may only enter a cell that is genuinely clear now (never one
        # another robot is "about to vacate" this tick — wait a full tick).
        occupied0 = {r.cell for r in sim.robots if r.alive}
        claimed = {}                       # cell -> robot.id

        for r in ordered:
            cur = r.cell
            tgt = r.pref_next or cur
            speed_cap = C.MAX_SPEED if r.connected else C.CAUTION_SPEED

            wait = (tgt == cur
                    or tgt in claimed
                    or tgt in occupied0
                    or not sim.world.is_free(*tgt))

            if not wait:
                claimed[tgt] = r.id
                self._wait_streak[r.id] = 0
                self._drive(r, tgt, speed_cap)
                self._housekeep(r)
                continue

            ws = self._wait_streak.get(r.id, 0) + 1
            self._wait_streak[r.id] = ws

            # (2) reactive detour: still blocked by another robot's body long
            #     past the threshold -> replan around that cell with D* Lite.
            if (tgt in occupied0 and ws > C.SW_DETOUR_TICKS and ws % 8 == 0
                    and r.goal_cell and r.path and len(r.path) > 1):
                alt = astar(sim.world, r.cell, r.goal_cell,
                            blocked=frozenset({tgt}))
                if alt and len(alt) > 1 and alt[1] != tgt:
                    extra = (len(alt) - 1) - (len(r.path) - 1)
                    if extra > 0:
                        sim.detour_events += 1
                        sim.detour_extra_cells += extra
                        sim._log(f"⚠ {r.name} stop-and-wait deadlock — "
                                 f"reactive detour (+{extra} cells)")
                    r.path = [tuple(c) for c in alt]
                    r.pref_next = r.path[1]
                    nxt = r.path[1]
                    if (nxt not in claimed and nxt not in occupied0
                            and sim.world.is_free(*nxt)):
                        claimed[nxt] = r.id
                        self._wait_streak[r.id] = 0
                        self._drive(r, nxt, speed_cap)
                        self._housekeep(r)
                        continue

            # still waiting: hold the current cell centre
            claimed.setdefault(cur, r.id)
            self._drive(r, cur, speed_cap)
            self._housekeep(r)
