"""The warehouse: a static occupancy grid plus pickup / drop-off / charging
stations.  grid[y, x] == True  means the cell is blocked.
"""
import numpy as np

from . import config as C


class World:
    def __init__(self):
        self.w = C.GRID_W
        self.h = C.GRID_H
        self.grid = np.zeros((self.h, self.w), dtype=bool)
        self.dynamic_obstacles = []          # (x, y) cells dropped at runtime
        self._build_static_layout()

        self.pickups = [tuple(p) for p in C.PICKUPS]
        self.dropoffs = [tuple(p) for p in C.DROPOFFS]
        self.chargers = [tuple(p) for p in C.CHARGERS]
        self.depot = [tuple(p) for p in C.DEPOT]      # standby parking bays

    # ------------------------------------------------------------------
    def _build_static_layout(self):
        g = self.grid
        g[0, :] = g[-1, :] = True
        g[:, 0] = g[:, -1] = True
        for (r0, r1) in C.SHELF_ROWS:
            for x in range(C.SHELF_X0, C.SHELF_X1):
                if x in C.SHELF_GAPS:
                    continue                 # vertical cross-aisle
                g[r0, x] = True
                g[r1, x] = True

    # ------------------------------------------------------------------
    def add_obstacle(self, x, y):
        x, y = int(x), int(y)
        if self.in_bounds(x, y) and not self.grid[y, x]:
            self.grid[y, x] = True
            self.dynamic_obstacles.append((x, y))
            return True
        return False

    def clear_obstacles(self):
        for (x, y) in self.dynamic_obstacles:
            self.grid[y, x] = False
        n = len(self.dynamic_obstacles)
        self.dynamic_obstacles = []
        return n

    def in_bounds(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def is_free(self, x, y):
        return self.in_bounds(x, y) and not self.grid[y, x]

    def neighbors4(self, x, y):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.is_free(nx, ny):
                yield nx, ny

    def static_obstacle_cells(self):
        """All blocked cells (walls + racks + dropped boxes) as [x, y] pairs -
        sent to the browser once so the map background can be drawn."""
        ys, xs = np.where(self.grid)
        return [[int(x), int(y)] for x, y in zip(xs, ys)]
