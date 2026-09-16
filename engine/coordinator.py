"""Layer 2 - decentralised multi-robot coordination: **MD-PIBT**
(PIBT with dynamic priorities + backtracking; Okumura et al., AIJ 2022).

The core routine is `algcore/md_pibt.py`.  This adapter runs one PIBT timestep
over the robots that should move, adding two things the warehouse sim needs and
the pure library deliberately leaves out:

* `reserved_static` - cells held by failed / charging robots, treated as walls;
* `congestion`      - a decaying traffic heat-map added to the move cost so
                      robots pick emptier aisles before a jam forms.

Priorities are dynamic exactly as in the paper: every robot has a unique base
value eta in [0,1); its priority rises by 1 each timestep it is not on its goal
and resets to eta on arrival, which guarantees progress and prevents starvation.
Higher-priority robots are served first and can push lower-priority robots out of
the way (priority inheritance); a failed push backtracks.  Vertex and swap
(edge) conflicts are both excluded.
"""
import numpy as np

from . import config as C


class PIBT:
    def __init__(self, world, seed=0):
        self.world = world
        self.rng = np.random.default_rng(seed)
        self._eta = {}
        self._boost = {}

    def _base_eta(self, rid):
        if rid not in self._eta:
            # unique, stable base priority in [0, 1)
            self._eta[rid] = (rid + 1) / (rid + 2)
            self._boost.setdefault(rid, 0.0)
        return self._eta[rid]

    def step(self, robots, dist_fields, congestion, reserved_static):
        """robots: robot objects that should move this tick.
        dist_fields: {robot_id: distance_field array}
        reserved_static: iterable of (x,y) cells to treat as walls.
        Returns {robot_id: (x, y)} next-cell assignment."""
        self.dist_fields = dist_fields
        self.congestion = congestion
        self.reserved_static = set(reserved_static)
        self.cur = {r.id: r.cell for r in robots}
        self.by_id = {r.id: r for r in robots}
        self.result = {}

        active_ids = {r.id for r in robots}
        for r in robots:
            self._base_eta(r.id)
            if r.id not in getattr(self, "_prev_ids", set()):
                self._boost[r.id] = 0.0          # robot (re)joined: fresh priority
        self._prev_ids = active_ids

        prio = {r.id: self._eta[r.id] + self._boost.get(r.id, 0.0) for r in robots}
        for r in sorted(robots, key=lambda r: prio[r.id], reverse=True):
            if r.id not in self.result:
                self._pibt(r, forbidden=None)

        # dynamic-priority update
        for r in robots:
            df = self.dist_fields[r.id]
            x, y = self.result.get(r.id, self.cur[r.id])
            at_goal = df[y, x] == 0
            self._boost[r.id] = 0.0 if at_goal else self._boost.get(r.id, 0.0) + 1.0

        return dict(self.result)

    # ------------------------------------------------------------------
    def _candidates(self, r):
        x, y = self.cur[r.id]
        df = self.dist_fields[r.id]
        cur_d = float(df[y, x])
        opts = [(x, y)] + list(self.world.neighbors4(x, y))
        self.rng.shuffle(opts)                       # random tie-break

        def cost(c):
            cx, cy = c
            base = float(df[cy, cx])
            # congestion only nudges the choice *among* cells that don't already
            # make progress, and is capped, so a free step toward the goal is
            # always taken and robots never flee backward into a corner.
            jam = 0.0
            if base >= cur_d:
                jam = min(float(self.congestion[cy, cx]),
                          C.CONGESTION_CAP) * C.CONGESTION_WEIGHT
            stay_pen = 0.35 if c == (x, y) else 0.0
            return base + jam + stay_pen

        opts.sort(key=cost)
        pref = getattr(r, "pref_next", None)
        if pref in opts and pref != (x, y):
            opts.remove(pref)
            opts.insert(0, pref)
        return opts

    def _pibt(self, r, forbidden):
        for c in self._candidates(r):
            if c in self.reserved_static:
                continue
            if c == forbidden:                       # swap / edge conflict
                continue
            if c in self.result.values():
                continue
            self.result[r.id] = c
            blocker = None
            for oid, ocell in self.cur.items():
                if ocell == c and oid != r.id and oid not in self.result:
                    blocker = self.by_id.get(oid)
            if blocker is None:
                return True
            if self._pibt(blocker, forbidden=self.cur[r.id]):
                return True
            del self.result[r.id]                     # backtrack
        self.result[r.id] = self.cur[r.id]
        return False
