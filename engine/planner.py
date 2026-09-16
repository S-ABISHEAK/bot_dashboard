"""Layer 1 - single-robot path planning.

* astar()          -> an explicit shortest path (kept name for callers; the
                      body now runs **D* Lite**, the incremental heuristic
                      replanner from `algcore/d_star_lite.py`).  Used for the
                      drawn route and to detect when a dropped obstacle
                      invalidates a plan.
* distance_field() -> backward-BFS cost-to-go map from the goal, used by
                      MD-PIBT (Layer 2) to rank candidate moves and for ETAs.
"""
import numpy as np

from . import config as C
from .algcore.d_star_lite import DStarLite


def _plan_dstar(grid, start, goal):
    d = DStarLite(grid, start, goal, connectivity=4)
    return d.plan()


def astar(world, start, goal, blocked=None):
    """4-connected shortest path on the occupancy grid via D* Lite.  Returns a
    list of (x, y) cells including start and goal, or None if unreachable.

    `blocked` (optional): an iterable of (x, y) cells to treat as walls for this
    query only, planned on a private copy of the grid (used for reactive detours
    around a robot that is not itself a grid obstacle)."""
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))
    if not world.is_free(*goal):
        return None
    if blocked:
        grid = np.array(world.grid, dtype=bool)          # private copy
        h, w = grid.shape
        for (x, y) in blocked:
            if 0 <= y < h and 0 <= x < w:
                grid[y, x] = True
        if grid[goal[1], goal[0]]:
            return None
    else:
        grid = np.asarray(world.grid, dtype=bool)        # fast path, no copy
    if not world.is_free(*start):
        # start cell got blocked (e.g. a box landed on the robot): plan from the
        # best free neighbour and stitch the original start back on.
        for nb in world.neighbors4(*start):
            sub = _plan_dstar(grid, nb, goal)
            if sub:
                return [start] + sub
        return None
    path = _plan_dstar(grid, start, goal)
    if path and len(path) >= 1:
        return [tuple(c) for c in path]
    return None


def distance_field(world, goal):
    """BFS cost-to-go from `goal` over free cells. Unreachable = large number."""
    INF = 10 ** 6
    df = np.full((world.h, world.w), INF, dtype=np.int32)
    if not world.is_free(*goal):
        return df
    gx, gy = goal
    df[gy, gx] = 0
    frontier = [(gx, gy)]
    while frontier:
        nxt = []
        for (x, y) in frontier:
            d = df[y, x] + 1
            for (nx, ny) in world.neighbors4(x, y):
                if d < df[ny, nx]:
                    df[ny, nx] = d
                    nxt.append((nx, ny))
        frontier = nxt
    return df
