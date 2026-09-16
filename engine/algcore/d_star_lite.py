"""
D* Lite  —  incremental heuristic path planner  (Koenig & Likhachev, 2002).

Working
    Searches backward from the goal to the start, maintaining for every cell a
    cost estimate g and a one-step-lookahead estimate rhs.  Cells with g != rhs
    ("locally inconsistent") sit on a priority queue keyed by
        k(s) = ( min(g,rhs) + h(start,s) + k_m ,  min(g,rhs) ).
    compute_shortest_path() expands inconsistent cells in key order until the
    start is consistent.  When edge costs change (a box is dropped or a lane
    clears) only the affected cells are made inconsistent and re-expanded, and a
    key modifier k_m absorbs the heuristic shift caused by the agent moving — so
    replanning repairs the old solution instead of rebuilding it.

Use
    The per-robot Layer-1 planner on a changing occupancy grid.  Produces the
    same optimal paths as A* but replans far fewer expansions after a local map
    change, which is exactly the warehouse case (dynamic obstacles, no full
    re-plan budget on an edge board).
"""
import heapq
import numpy as np

INF = float("inf")


class DStarLite:
    def __init__(self, grid, start, goal, connectivity=8):
        self.grid = np.asarray(grid, dtype=bool).copy()
        self.h, self.w = self.grid.shape
        self.start = tuple(start)
        self.goal = tuple(goal)
        self.conn = connectivity
        self.k_m = 0.0
        self._s_last = self.start
        self.g = {}
        self.rhs = {self.goal: 0.0}
        self.U = []
        self.U_keys = {}
        self.expansions = 0
        self._push(self.goal, self._key(self.goal))

    # -- helpers -------------------------------------------------------
    def _gv(self, s):
        return self.g.get(s, INF)

    def _rv(self, s):
        return self.rhs.get(s, INF)

    def _h(self, a, b):
        dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
        if self.conn == 8:
            return (dx + dy) + (2.0 ** 0.5 - 2.0) * min(dx, dy)
        return dx + dy

    def _steps(self):
        if self.conn == 8:
            return ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                    (0, 1), (1, -1), (1, 0), (1, 1))
        return ((-1, 0), (1, 0), (0, -1), (0, 1))

    def _succ(self, s):
        x, y = s
        for dx, dy in self._steps():
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.w and 0 <= ny < self.h and not self.grid[ny, nx]:
                yield (nx, ny)

    def _cost(self, a, b):
        if self.grid[a[1], a[0]] or self.grid[b[1], b[0]]:
            return INF
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def _key(self, s):
        m = min(self._gv(s), self._rv(s))
        return (m + self._h(self.start, s) + self.k_m, m)

    def _push(self, s, key):
        self.U_keys[s] = key
        heapq.heappush(self.U, (key, s))

    def _top(self):
        while self.U:
            key, s = self.U[0]
            if self.U_keys.get(s) == key:
                return key, s
            heapq.heappop(self.U)
        return (INF, INF), None

    def _update_vertex(self, u):
        if u != self.goal:
            self.rhs[u] = min((self._cost(u, sp) + self._gv(sp)
                               for sp in self._succ(u)), default=INF)
        self.U_keys.pop(u, None)
        if self._gv(u) != self._rv(u):
            self._push(u, self._key(u))

    # -- main routine -----------------------------------------------
    def compute_shortest_path(self):
        while True:
            k_old, u = self._top()
            if u is None:
                break
            if not (k_old < self._key(self.start)
                    or self._rv(self.start) != self._gv(self.start)):
                break
            heapq.heappop(self.U)
            self.U_keys.pop(u, None)
            self.expansions += 1
            k_new = self._key(u)
            if k_old < k_new:
                self._push(u, k_new)
            elif self._gv(u) > self._rv(u):
                self.g[u] = self._rv(u)
                for s in self._succ(u):
                    self._update_vertex(s)
            else:
                self.g[u] = INF
                for s in list(self._succ(u)) + [u]:
                    self._update_vertex(s)

    # -- public API -------------------------------------------------
    def plan(self):
        """Walk from the current start to the goal, re-consistifying the search
        as the start moves (the D* Lite Main() loop).  Returns the traversed
        cell list, or None if the goal is unreachable.  Leaves `start` at the
        goal; call set_start() before re-using the planner."""
        self.compute_shortest_path()
        if self._gv(self.start) == INF:
            return None
        path, guard = [self.start], 0
        while self.start != self.goal:
            nxt = min(self._succ(self.start),
                      key=lambda sp: self._cost(self.start, sp) + self._gv(sp),
                      default=None)
            if nxt is None or self._cost(self.start, nxt) + self._gv(nxt) == INF:
                return None
            self.set_start(nxt)
            self.compute_shortest_path()
            path.append(nxt)
            guard += 1
            if guard > self.w * self.h:
                return None
        return path

    def set_start(self, cell):
        cell = tuple(cell)
        self.k_m += self._h(self._s_last, cell)
        self._s_last = cell
        self.start = cell

    def update_cells(self, changes):
        """changes: iterable of (x, y, blocked_bool).  Applies them to the grid
        and repairs the plan incrementally."""
        touched = set()
        for x, y, blocked in changes:
            if bool(self.grid[y, x]) == bool(blocked):
                continue
            self.grid[y, x] = bool(blocked)
            touched.add((x, y))
            for dx, dy in self._steps():
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.w and 0 <= ny < self.h:
                    touched.add((nx, ny))
        for c in touched:
            self._update_vertex(c)
        self.compute_shortest_path()


# ------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(7)
    W, H = 60, 40
    grid = rng.random((H, W)) < 0.12            # ~12% random obstacles
    start, goal = (1, 1), (W - 2, H - 2)
    grid[start[1], start[0]] = grid[goal[1], goal[0]] = False

    def cost(p):
        return round(sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                         for a, b in zip(p, p[1:])), 2)

    d = DStarLite(grid, start, goal, connectivity=8)
    p1 = d.plan()
    assert p1 and p1[0] == start and p1[-1] == goal
    assert all(not grid[y, x] for x, y in p1)
    print(f"cold traverse                : cost={cost(p1):6.1f}")

    # a box appears on the middle of the route (still leaving the goal reachable)
    box = None
    for c in p1[len(p1) // 2:len(p1) - 2] + list(reversed(p1[2:len(p1) // 2])):
        g2 = grid.copy()
        g2[c[1], c[0]] = True
        if DStarLite(g2, start, goal, connectivity=8).plan() is not None:
            box = c
            break
    assert box is not None

    d.set_start(start)
    d.expansions = 0
    d.update_cells([(box[0], box[1], True)])
    p2 = d.plan()
    inc = d.expansions
    assert p2 and box not in p2 and all(not d.grid[y, x] for x, y in p2)
    assert cost(p2) >= cost(p1)
    print(f"incremental repair + traverse: cost={cost(p2):6.1f}  expansions={inc}")

    fresh = DStarLite(d.grid, start, goal, connectivity=8)
    fresh.plan()
    print(f"from-scratch replan + traverse:               expansions={fresh.expansions}")

    d.update_cells([(box[0], box[1], False)])
    d.set_start(start)
    assert cost(d.plan()) == cost(p1)
    print("box cleared                  : original route restored")

    assert inc < fresh.expansions, "incremental repair must expand fewer cells than a cold replan"
    print("OK")
