"""Robot state + simple holonomic kinematics."""
import numpy as np

from . import config as C


# phase values: idle | to_pickup | to_dropoff | to_charge | charging | failed
class Robot:
    def __init__(self, rid, name, start_cell, color, priority, battery=100.0):
        self.id = rid
        self.name = name
        self.color = color
        self.priority = priority
        self.pos = np.array([start_cell[0] + 0.5, start_cell[1] + 0.5], float)
        self.vel = np.zeros(2)

        self.task = None
        self.phase = "idle"
        self.goal_cell = None
        self.path = []
        self.pref_next = None

        self.alive = True
        self.connected = True
        self.avoiding = False
        self.was_avoiding = False
        self.battery = float(battery)

        self.last_progress_tick = 0
        self.last_cell = self.cell
        self.stall_ticks = 0
        self.kick_dir = None
        self.moving_ticks = 0
        self.reroute_tick = -999
        self.charger_cell = None

        # rate-limited planning + degraded "safe-hold" state
        self.plan_cooldown = 0        # don't call A* again until this tick
        self.plan_map_version = -1    # map version the current plan was made for
        self.stranded = False         # no reachable route to goal -> holding
        self.stranded_since = None
        self.parked = False           # idle robot has retired off the aisles

    # ------------------------------------------------------------------
    @property
    def cell(self):
        return (int(self.pos[0]), int(self.pos[1]))

    @property
    def speed(self):
        return float(np.linalg.norm(self.vel))

    def assign_task(self, task):
        self.task = task
        self.phase = "to_pickup"
        self.goal_cell = tuple(task.pickup)
        self.path = []
        self.stranded = False
        self.stranded_since = None
        self.plan_cooldown = 0
        self.parked = False

    def clear_task(self):
        self.task = None
        self.phase = "idle"
        self.goal_cell = None
        self.path = []
        self.pref_next = None
        self.stranded = False
        self.stranded_since = None
        self.plan_cooldown = 0
        self.parked = False               # set once the idle robot has retired

    def integrate(self, chosen_vel, speed_cap):
        v = chosen_vel
        n = np.linalg.norm(v)
        if n > speed_cap:
            v = v / n * speed_cap
        self.vel = v
        self.pos = self.pos + v * C.DT
