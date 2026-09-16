"""
MD-PIBT  —  decentralised multi-agent path finding
            (PIBT: Priority Inheritance with Backtracking + dynamic priorities;
             Okumura, Machida, Defago, Tamura, AIJ 2022).

Working
    One grid timestep at a time.  Every agent has a priority; agents are served
    highest-first.  A served agent picks the free neighbouring cell that most
    reduces its own distance-to-goal (a per-goal BFS field).  If the chosen cell
    is held by a lower-priority agent, that agent *inherits* the mover's demand
    and is recursively pushed out of the way first; if the push fails the mover
    *backtracks* and tries its next-best cell.  Swap (edge) conflicts are
    forbidden by refusing the caller's origin cell.  Priorities are *dynamic*:
    an agent's priority rises by 1 every step it is not on its goal and resets
    to its unique base value once it arrives — this guarantees progress and
    prevents starvation in a lifelong / warehouse (MAPD) setting.

Use
    The Layer-2 coordinator for a decentralised warehouse swarm: each agent only
    needs its immediate neighbours' intended moves, it runs in near-constant
    time per step regardless of fleet size, and it never stalls the whole fleet.
    (For an offline, completeness-guaranteed plan, PIBT is used as the
    successor generator inside LaCAM search — out of scope here.)
"""
from collections import deque
import numpy as np


class PIBT:
    def __init__(self, grid, starts, goals, seed=0):
        self.grid = np.asarray(grid, dtype=bool)
        self.h, self.w = self.grid.shape
        self.N = len(starts)
        self.pos = [tuple(s) for s in starts]
        self.goal = [tuple(g) for g in goals]
        self.rng = np.random.default_rng(seed)
        base = list(np.linspace(0.0, 1.0, self.N, endpoint=False))
        self.rng.shuffle(base)
        self.eta = base                      # unique base priority in [0, 1)
        self.prio = list(self.eta)
        self._field = {}

    # -- grid helpers ---------------------------------------------------
    def _neighbours(self, c):
        x, y = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.w and 0 <= ny < self.h and not self.grid[ny, nx]:
                yield (nx, ny)

    def _dist(self, goal):
        if goal not in self._field:
            INF = 1 << 30
            f = np.full((self.h, self.w), INF, dtype=np.int64)
            if not self.grid[goal[1], goal[0]]:
                f[goal[1], goal[0]] = 0
                q = deque([goal])
                while q:
                    cx, cy = q.popleft()
                    for nx, ny in self._neighbours((cx, cy)):
                        if f[ny, nx] > f[cy, cx] + 1:
                            f[ny, nx] = f[cy, cx] + 1
                            q.append((nx, ny))
            self._field[goal] = f
        return self._field[goal]

    def _candidates(self, i):
        f = self._dist(self.goal[i])
        cur = self.pos[i]
        opts = [cur] + list(self._neighbours(cur))
        self.rng.shuffle(opts)                       # random tie-break (escapes livelocks)
        opts.sort(key=lambda c: f[c[1], c[0]])
        return opts

    # -- one timestep -------------------------------------------------
    def step(self):
        self._from = list(self.pos)
        self._at = {p: k for k, p in enumerate(self._from)}
        self._to = {}
        for i in sorted(range(self.N), key=lambda k: self.prio[k], reverse=True):
            if i not in self._to:
                self._pibt(i, None)
        self.pos = [self._to[i] for i in range(self.N)]
        for i in range(self.N):
            self.prio[i] = (self.eta[i] if self.pos[i] == self.goal[i]
                            else self.prio[i] + 1.0)
        return {i: self.pos[i] for i in range(self.N)}

    def _pibt(self, i, forbidden):
        for v in self._candidates(i):
            if v in self._to.values():
                continue
            if v == forbidden:
                continue
            self._to[i] = v
            k = self._at.get(v)
            if k is not None and k != i and k not in self._to:
                if self._pibt(k, self._from[i]):
                    return True
                del self._to[i]
                continue
            return True
        self._to[i] = self._from[i]
        return False

    # -- full scenario ----------------------------------------------
    def all_done(self):
        return all(self.pos[i] == self.goal[i] for i in range(self.N))

    def run(self, max_steps):
        hist = {i: [self.pos[i]] for i in range(self.N)}
        for _ in range(max_steps):
            if self.all_done():
                break
            self.step()
            for i in range(self.N):
                hist[i].append(self.pos[i])
        return hist


def check(hist):
    N = len(hist)
    T = len(next(iter(hist.values())))
    for t in range(T):
        cells = [hist[i][t] for i in range(N)]
        assert len(set(cells)) == N, f"vertex collision at t={t}: {cells}"
        if t + 1 < T:
            for i in range(N):
                for j in range(i + 1, N):
                    if hist[i][t] == hist[j][t + 1] and hist[j][t] == hist[i][t + 1]:
                        raise AssertionError(f"edge swap {i}<->{j} at t={t}")


# ------------------------------------------------------------------
if __name__ == "__main__":
    # (a) head-on in a 2-wide corridor: agents sidestep past each other
    corr = np.ones((4, 12), dtype=bool)
    corr[1:3, :] = False
    p = PIBT(corr,
             starts=[(0, 1), (0, 2), (11, 1), (11, 2)],
             goals=[(11, 1), (11, 2), (0, 1), (0, 2)])
    h = p.run(max_steps=512)
    check(h)
    assert p.all_done(), "all 4 agents should pass and reach their goals"
    print(f"2-wide head-on : solved, makespan {max(len(v) for v in h.values()) - 1}")

    # (b) two rooms joined by a single 1-wide door; 3 agents cross each way and
    #     must queue through the door in priority order
    H, W = 9, 15
    g = np.zeros((H, W), dtype=bool)
    g[:, 7] = True
    g[4, 7] = False                                  # the door
    starts = [(1, 1), (1, 4), (1, 7), (13, 1), (13, 4), (13, 7)]
    goals = [(13, 7), (13, 4), (13, 1), (1, 7), (1, 4), (1, 1)]
    p = PIBT(g, starts, goals)
    h = p.run(max_steps=512)
    check(h)
    assert p.all_done(), "all 6 agents should get through the door"
    door_seq = [i for t in range(len(h[0])) for i in range(6) if h[i][t] == (7, 4)]
    print(f"single door    : solved, makespan {max(len(v) for v in h.values()) - 1}, "
          f"{len(door_seq)} door traversals, no conflicts")

    # (c) 8 agents on an open floor, goals = a shuffled permutation of starts
    rng = np.random.default_rng(3)
    H, W = 14, 18
    g = np.zeros((H, W), dtype=bool)
    cells = [(x, y) for x in range(1, W - 1) for y in range(1, H - 1)]
    picked = rng.choice(len(cells), size=16, replace=False)
    starts = [cells[k] for k in picked[:8]]
    goals = [cells[k] for k in picked[8:]]
    p = PIBT(g, starts, goals)
    h = p.run(max_steps=512)
    check(h)
    assert p.all_done(), "all 8 agents should reach their goals"
    print(f"8-agent floor  : solved, makespan {max(len(v) for v in h.values()) - 1}, "
          f"no vertex/edge conflicts")
    print("OK")
