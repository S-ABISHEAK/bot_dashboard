"""Wires the five algorithm layers into one tick loop and produces a rich JSON
snapshot per tick for the live dashboard.

The layer implementations live in planner.py / coordinator.py / avoidance.py /
allocator.py / comms.py and each delegates to the reference algorithm in
engine/algcore/ (vendored from the repo-root algorithms/ folder):

Per tick:
  0. scripted events (only when scripted=True; the dashboard injects live instead)
  1. comms: each connected robot publishes its pose over the Zenoh-style mesh
  2. battery drain + low-battery divert-to-charger
  3. Layer 4  ACBBA    -> bundle + consensus allocation of queued tasks
  4. Layer 1  D* Lite   -> per-robot route to its current sub-goal / charger
  5. Layer 2  MD-PIBT   -> conflict-free next grid cell for every moving robot
  6. Layer 3  NH-ORCA   -> continuous velocity that also dodges close robots
  7. integrate kinematics, charging, congestion map, heartbeat, KPI accumulators
"""
from collections import deque
import numpy as np

from . import config as C
from .world import World
from .robot import Robot
from .planner import astar, distance_field
from .coordinator import PIBT
from .allocator import Task, Allocator
from .comms import CommsBus
from .strategies import StackStrategy, StopWaitStrategy


def _c(cell):
    return np.array([cell[0] + 0.5, cell[1] + 0.5], float)


class Simulation:
    def __init__(self, n_robots=C.N_ROBOTS, n_tasks=C.N_TASKS,
                 seed=C.RANDOM_SEED, scripted=False, coordination="stack",
                 custom_layout=None):
        self.n = int(max(1, min(C.MAX_ROBOTS, n_robots)))
        self.n_tasks = int(max(1, min(C.MAX_TASKS, n_tasks)))
        self.seed = int(seed)
        self.scripted = scripted
        self.coordination = coordination
        self._cfg = dict(n_robots=self.n, n_tasks=self.n_tasks, seed=self.seed,
                         custom_layout=bool(custom_layout))

        self.rng = np.random.default_rng(self.seed)
        self.world = World(custom_layout=custom_layout)
        self.pibt = PIBT(self.world, seed=self.seed)
        self.coord = (StopWaitStrategy() if coordination == "stopwait"
                      else StackStrategy())
        self.comms = CommsBus()
        self.tick = 0
        self.dashboard_online = True
        self.dashboard_kill_tick = None
        self.events_note = ""
        self._df_cache = {}
        self._map_version = 0

        starts = self._resolve_robot_starts(custom_layout)
        self.robots = [
            Robot(i, C.ROBOT_NAMES[i], starts[i], C.ROBOT_COLORS[i],
                  priority=i, battery=float(self.rng.uniform(*C.BATTERY_START)))
            for i in range(self.n)
        ]
        self.congestion = np.zeros((self.world.h, self.world.w), dtype=float)

        self.alloc = Allocator(self._make_tasks())
        self.priority_order = deque(range(self.n))
        self.snapshots = []

        # KPI accumulators
        self.kpi_conflicts = 0
        self.kpi_near_miss = 0
        self.kpi_avoided = 0
        self._close_pairs = set()
        self.event_log = []
        self._log_synced = 0
        self._activity = dict(astar_replans=0, astar_replans_tick=0,
                              pibt_pushes_tick=0, avoiding_now=0)

        # benchmark metrics (deadlock / makespan / stop-and-wait detour cost)
        self.stuck_ticks = {}
        self.deadlock_robot_ticks = 0
        self.makespan_tick = None
        self.detour_events = 0
        self.detour_extra_cells = 0
        self.dist_travelled_cells = 0.0

    # ------------------------------------------------------------------
    def cfg(self):
        return dict(self._cfg)

    def _make_tasks(self):
        p, d = self.world.pickups, self.world.dropoffs
        tasks = []
        for i in range(self.n_tasks):
            a = tuple(p[int(self.rng.integers(len(p)))])
            b = tuple(d[int(self.rng.integers(len(d)))])
            tasks.append(Task(i, a, b))
        return tasks

    def _resolve_robot_starts(self, custom_layout):
        """Where each robot spawns.  Default layout keeps the scripted
        ROBOT_STARTS positions unchanged; a custom layout has no such list,
        so robots start in depot bays (falling back to any free, non-station
        cell if there aren't enough bays for the fleet size)."""
        if custom_layout is None:
            return [C.ROBOT_STARTS[i] for i in range(self.n)]
        starts = list(self.world.depot[:self.n])
        if len(starts) < self.n:
            taken = (set(self.world.pickups) | set(self.world.dropoffs)
                     | set(self.world.chargers) | set(starts))
            for y in range(self.world.h):
                for x in range(self.world.w):
                    if len(starts) >= self.n:
                        break
                    if self.world.is_free(x, y) and (x, y) not in taken:
                        starts.append((x, y))
                        taken.add((x, y))
                if len(starts) >= self.n:
                    break
        return starts[:self.n]

    # ------------------------------------------------------------------
    def _distance_field(self, goal):
        key = (goal, self._map_version)
        if key not in self._df_cache:
            self._df_cache[key] = distance_field(self.world, goal)
        return self._df_cache[key]

    def _depot_slots(self):
        """The numbered standby / completion parking bays (map geometry)."""
        return self.world.depot

    def _idle_home(self, r):
        """The parking bay this idle robot should head for (a stable, unique
        assignment), or None if no depot is configured."""
        slots = self._depot_slots()
        if not slots:
            return None
        occupied = {rb.cell for rb in self.robots
                    if rb is not r and rb.parked}
        occupied |= {rb.goal_cell for rb in self.robots
                     if rb is not r and not rb.parked and rb.goal_cell in slots}
        if r.goal_cell in slots and r.goal_cell not in occupied:
            return r.goal_cell                            # sticky: keep my bay
        free = [s for s in slots if s not in occupied] or slots
        return min(free, key=lambda s: abs(s[0] - r.cell[0])
                   + abs(s[1] - r.cell[1]))

    def _dock(self, r, bay):
        """Snap a robot precisely into a parking bay and freeze it."""
        r.pos[:] = (bay[0] + 0.5, bay[1] + 0.5)
        r.vel[:] = 0
        r.parked = True
        r.goal_cell = None
        r.path = []

    def _static_cells_near(self, pos, rad=2):
        cx, cy = int(pos[0]), int(pos[1])
        out = []
        for y in range(cy - rad, cy + rad + 1):
            for x in range(cx - rad, cx + rad + 1):
                if self.world.in_bounds(x, y) and self.world.grid[y, x]:
                    out.append((x, y))
        return out

    def _shove_to_free(self, r):
        if self.world.is_free(*r.cell):
            return
        best, bd = None, 1e9
        for y in range(r.cell[1] - 2, r.cell[1] + 3):
            for x in range(r.cell[0] - 2, r.cell[0] + 3):
                if self.world.is_free(x, y):
                    dd = abs(x + 0.5 - r.pos[0]) + abs(y + 0.5 - r.pos[1])
                    if dd < bd:
                        bd, best = dd, (x, y)
        if best:
            r.pos = np.array([best[0] + 0.5, best[1] + 0.5], float)
            r.vel[:] = 0
            r.path = []

    def _log(self, msg):
        self.event_log.append({"t": round(self.tick * C.DT, 1), "msg": msg})
        self.event_log = self.event_log[-60:]
        self.events_note = msg

    # ------------------------------------------------------------------
    def inject_event(self, kind, payload=None):
        if kind == "obstacle":
            p = [int(v) for v in payload]
            if len(p) >= 4:
                x0, y0, w, h = p[0], p[1], max(1, p[2]), max(1, p[3])
                cells = [(x, y) for x in range(x0, x0 + w)
                         for y in range(y0, y0 + h)]
            else:
                cells = [(p[0], p[1])]
            added = [(x, y) for (x, y) in cells if self.world.add_obstacle(x, y)]
            if added:
                self._map_version += 1
                self._df_cache.clear()
                for r in self.robots:
                    r.path = []
                    self._shove_to_free(r)
                if len(added) == 1:
                    self._log(f"Box dropped at ({added[0][0]},{added[0][1]}) "
                              f"— D* Lite re-plans around it")
                else:
                    self._log(f"Obstacle block of {len(added)} cells dropped "
                              f"— D* Lite re-plans around it")
        elif kind == "dead_zone":
            self.comms.add_dead_zone(tuple(payload))
            self._log("Wi-Fi dead zone added — robots inside go CONNECTIVITY_LOST")
        elif kind in ("dead_zone_clear", "clear_zones"):
            self.comms.clear_dead_zones()
            self._log("Dead zones cleared — fleet rejoins the mesh")
        elif kind in ("clear_obstacles", "clear_boxes"):
            n = self.world.clear_obstacles()
            if n:
                self._map_version += 1
                self._df_cache.clear()
                for r in self.robots:
                    r.path = []
                unblocked = 0
                for t in self.alloc.tasks:
                    if t.status == "blocked":
                        t.status = "queued"
                        t.fail_count = 0
                        unblocked += 1
                extra = f", {unblocked} blocked task(s) re-queued" if unblocked else ""
                self._log(f"{n} box(es) removed — routes re-open{extra}")
        elif kind == "robot_fail":
            i = int(payload)
            if 0 <= i < self.n and self.robots[i].alive:
                r = self.robots[i]
                r.alive = False
                r.phase = "failed"
                r.vel[:] = 0
                self.alloc.reopen(r.id, "robot fault", self.tick)
                r.clear_task()
                r.phase = "failed"
                self._log(f"{r.name} FAULT — ACBBA re-auctions its task")
        elif kind == "robot_recover":
            i = int(payload)
            if 0 <= i < self.n and not self.robots[i].alive:
                r = self.robots[i]
                r.alive = True
                r.phase = "idle"
                r.stranded = False
                r.stranded_since = None
                r.plan_cooldown = 0
                self._shove_to_free(r)
                self._log(f"{r.name} back online")
        elif kind == "dashboard_kill":
            self.dashboard_online = False
            self.dashboard_kill_tick = self.tick
            self._log("Central dashboard killed — fleet keeps running (decentralised)")

    def _scripted_events(self):
        ev = C.EVENTS.get(self.tick)
        if ev:
            self.inject_event(*ev)

    # ------------------------------------------------------------------
    def _nearest_charger(self, r):
        free = []
        taken = {rob.charger_cell for rob in self.robots
                 if rob is not r and rob.charger_cell}
        for ch in self.world.chargers:
            if ch in taken:
                continue
            df = self._distance_field(ch)
            free.append((df[r.cell[1], r.cell[0]], ch))
        if not free:
            free = [(self._distance_field(ch)[r.cell[1], r.cell[0]], ch)
                    for ch in self.world.chargers]
        free.sort(key=lambda z: z[0])
        return free[0][1]

    def _battery_and_charging(self):
        for r in self.robots:
            if not r.alive:
                continue
            if r.phase == "charging":
                r.battery = min(100.0, r.battery + C.BATTERY_CHARGE_RATE)
                if r.battery >= C.BATTERY_FULL:
                    r.phase = "idle"
                    r.goal_cell = None
                    r.charger_cell = None
                    self._log(f"{r.name} charged to {r.battery:.0f}% — back in service")
                continue
            drain = C.BATTERY_DRAIN_MOVE if r.speed > 0.05 else C.BATTERY_DRAIN_IDLE
            r.battery = max(0.0, r.battery - drain)
            if (r.phase not in ("to_charge",) and r.battery < C.BATTERY_LOW):
                if r.task is not None:
                    self.alloc.reopen(r.id, "low battery", self.tick)
                r.clear_task()
                r.phase = "to_charge"
                r.charger_cell = self._nearest_charger(r)
                r.goal_cell = r.charger_cell
                r.path = []
                self._log(f"{r.name} low battery ({r.battery:.0f}%) — diverting to charger")

    def _enter_safe_hold(self, r):
        """(3) Degraded 'safe-hold': the robot has no reachable route to its
        goal.  It stops where it is, its task is released for re-auction, and an
        alert is logged.  A charge trip is kept (it keeps retrying on the
        back-off timer in case the blockage clears)."""
        first = not r.stranded
        r.stranded = True
        r.vel[:] = 0
        if r.stranded_since is None:
            r.stranded_since = self.tick
        if not first:
            return
        if r.task is not None:
            t = r.task
            t.fail_count += 1
            self.alloc.reopen(r.id, "goal unreachable", self.tick)
            r.clear_task()
            if t.fail_count >= 3:
                t.status = "blocked"
                self._log(f"⚠ task {t.id} BLOCKED — unreachable for the whole "
                          f"fleet; needs manual intervention")
            else:
                self._log(f"⚠ {r.name} safe-hold — no route to goal; "
                          f"task {t.id} released for re-auction")
        elif r.phase == "to_charge":
            self._log(f"⚠ {r.name} safe-hold — no route to a charger; "
                      f"holding position, retrying")

    # ------------------------------------------------------------------
    def step(self):
        if self.scripted:
            self._scripted_events()
        self.tick += 1
        self._activity["astar_replans_tick"] = 0
        self._activity["pibt_pushes_tick"] = 0

        # 1. comms publish
        for r in self.robots:
            if r.alive:
                r.connected = self.comms.publish(r.id, r.pos, r.vel, self.tick)

        # 2. battery + charging divert
        self._battery_and_charging()

        # 3. Layer 4: ACBBA auction
        if self.tick % C.REAUCTION_EVERY == 1 or self.alloc.open_tasks():
            self.alloc.auction(
                self.robots,
                lambda rr, cell: abs(rr.cell[0] - cell[0]) + abs(rr.cell[1] - cell[1]),
                self.tick,
            )
        for entry in self.alloc.log[self._log_synced:]:
            self.event_log.append({"t": round(self.tick * C.DT, 1), "msg": entry})
        self._log_synced = len(self.alloc.log)
        self.event_log = self.event_log[-60:]

        if self.tick % 30 == 0:
            self.priority_order.rotate(1)

        # 4. Layer 1: A* to current sub-goal / charger
        active = []
        for r in self.robots:
            if not r.alive or r.phase in ("charging",):
                continue
            if r.task is None and r.phase != "to_charge":
                # idle: retire to a numbered standby bay in the depot so a
                # jobless robot never lingers in a pickup / drop-off aisle.
                if r.parked:
                    r.goal_cell = None
                    r.path = []
                    continue
                home = self._idle_home(r)
                if home is None:
                    r.parked = True
                    r.goal_cell = None
                    r.path = []
                    continue
                if (abs(r.pos[0] - (home[0] + 0.5))
                        + abs(r.pos[1] - (home[1] + 0.5))) < 1.1:
                    self._dock(r, home)           # close enough — snap into the bay
                    continue
                r.goal_cell = home

            if r.goal_cell and np.linalg.norm(r.pos - _c(r.goal_cell)) < 0.45:
                if r.phase == "to_pickup":
                    r.phase = "to_dropoff"
                    r.goal_cell = tuple(r.task.dropoff)
                    r.path = []
                elif r.phase == "to_dropoff":
                    r.task.status = "done"
                    r.task.done_tick = self.tick
                    self.alloc.log.append(f"t{self.tick}: task {r.task.id} DONE by {r.name}")
                    r.clear_task()
                    continue
                elif r.phase == "to_charge":
                    r.phase = "charging"
                    r.vel[:] = 0
                    self._log(f"{r.name} docked at charger ({r.battery:.0f}%)")
                    continue
                elif r.task is None:
                    self._dock(r, r.goal_cell)      # arrived at the bay — snap in
                    continue

            blocked = any(self.world.grid[y, x] for (x, y) in r.path)
            off_path = True
            j = 0
            if r.path and len(r.path) > 1:
                ds = [abs(px + 0.5 - r.pos[0]) + abs(py + 0.5 - r.pos[1])
                      for (px, py) in r.path]
                j = int(np.argmin(ds))
                off_path = ds[j] > 2.5

            need_replan = ((not r.path) or blocked or off_path
                           or r.path[-1] != r.goal_cell)
            map_changed = r.plan_map_version != self._map_version
            # (1) rate-limited / event-driven planning: after a failed plan we
            # back off REPLAN_BACKOFF ticks unless the map changed - no more
            # thousands of A* calls when a goal is walled off.
            if need_replan and (self.tick >= r.plan_cooldown or map_changed):
                if blocked and r.task is not None and not r.task.rerouted:
                    r.task.rerouted = True
                    r.reroute_tick = self.tick
                path = astar(self.world, r.cell, r.goal_cell)
                r.plan_map_version = self._map_version
                self._activity["astar_replans"] += 1
                self._activity["astar_replans_tick"] += 1
                if path and len(path) > 1:
                    r.path = path
                    j = 0
                    r.plan_cooldown = 0
                    if r.stranded:
                        r.stranded = False
                        r.stranded_since = None
                        self._log(f"{r.name} route restored — resuming")
                else:
                    # (3) no reachable route -> degraded safe-hold
                    j = 0
                    r.plan_cooldown = self.tick + C.REPLAN_BACKOFF
                    self._enter_safe_hold(r)   # may release the task -> idle
                    if r.task is None and r.phase != "to_charge":
                        continue                # now idle, nothing to move
                    r.path = [r.cell]

            if not r.path:
                r.path = [r.cell]
                j = 0
            r.pref_next = r.path[min(j + 1, len(r.path) - 1)]
            active.append(r)

        # robots that will not be moved this tick must not keep a stale velocity
        # (a non-zero r.vel would drain battery as if the robot were driving).
        _act = set(active)
        for r in self.robots:
            if r.alive and r not in _act:
                r.vel[:] = 0

        # 5+6. Layer 2 (MD-PIBT) + Layer 3 (NH-ORCA) — pluggable coordination
        self.coord.move(self, active)

        # 7. congestion, heartbeat, near-miss, utilisation
        self.congestion *= C.CONGESTION_DECAY
        self.dist_travelled_cells += sum(
            r.speed for r in self.robots if r.alive) * C.DT
        for r in self.robots:
            if r.alive:
                self.congestion[r.cell[1], r.cell[0]] += 1.0
                if r.speed > 0.05:
                    r.moving_ticks += 1
            if r.cell != r.last_cell:
                r.last_cell = r.cell
                r.last_progress_tick = self.tick
            if (r.alive and r.task and
                    self.tick - r.last_progress_tick > C.HEARTBEAT_TIMEOUT):
                self.alloc.reopen(r.id, "heartbeat timeout", self.tick)
                r.clear_task()
                r.last_progress_tick = self.tick
                self.kpi_conflicts += 1

        alive = [r for r in self.robots if r.alive]
        now_close = set()
        for i in range(len(alive)):
            for k in range(i + 1, len(alive)):
                # count a "collision" episode only on genuine body overlap
                if np.linalg.norm(alive[i].pos - alive[k].pos) < 1.7 * C.ROBOT_RADIUS:
                    key = (alive[i].id, alive[k].id)
                    now_close.add(key)
                    if key not in self._close_pairs:
                        self.kpi_near_miss += 1        # count episodes, not ticks
        self._close_pairs = now_close

        self._activity["avoiding_now"] = sum(1 for r in self.robots if r.avoiding)

        # benchmark: stuck-robot / deadlock / makespan tracking
        for r in self.robots:
            stuck = (r.alive and r.goal_cell is not None
                     and r.phase != "charging" and r.speed < 0.05)
            self.stuck_ticks[r.id] = (self.stuck_ticks.get(r.id, 0) + 1
                                      if stuck else 0)
            if self.stuck_ticks[r.id] > C.STUCK_TICKS:
                self.deadlock_robot_ticks += 1
        if (self.makespan_tick is None
                and self.alloc.done_count() == len(self.alloc.tasks)):
            self.makespan_tick = self.tick

        self.snapshots.append(self._snapshot())

    # ------------------------------------------------------------------
    def _eta(self, r):
        if not r.goal_cell:
            return None
        df = self._distance_field(r.goal_cell)
        rem = float(df[r.cell[1], r.cell[0]])
        if rem > 1e5:
            return None
        if r.phase == "to_pickup" and r.task:
            rem += abs(r.task.pickup[0] - r.task.dropoff[0]) + \
                   abs(r.task.pickup[1] - r.task.dropoff[1])
        return round(rem / C.MAX_SPEED, 1)

    def _task_eta(self, t):
        if t.status != "active" or t.assignee is None:
            return None
        return self._eta(self.robots[t.assignee])

    def _aisle(self, cell):
        return f"A{max(1, min(9, 1 + (cell[0] - 1) * 9 // max(1, self.world.w - 2))):02d}"

    def _bay(self, cell):
        return f"B{max(1, cell[1]):02d}"

    def _mode(self, r):
        if not r.alive:
            return "error"
        if r.stranded:
            return "stranded"
        if r.phase in ("charging", "to_charge"):
            return "charging"
        if not r.connected:
            return "comms-lost"
        if r.parked:
            return "parked"
        if r.task is None:
            return "idle"
        if self.tick - r.reroute_tick < 45:
            return "rerouting"
        if r.speed < 0.05:
            return "waiting"
        return "active"

    def _task_label(self, r):
        if r.parked:
            d = self.world.depot
            slot = min(range(len(d)),
                       key=lambda i: abs(d[i][0] - r.cell[0])
                       + abs(d[i][1] - r.cell[1]))
            return f"Parked · depot bay {slot + 1}"
        if r.stranded:
            return "SAFE-HOLD · no route to goal"
        if r.phase == "to_charge":
            return "Return to charger"
        if r.phase == "charging":
            return "Charging"
        if not r.task:
            return "Idle"
        if r.phase == "to_pickup":
            return f"Pick @ {self._aisle(r.task.pickup)}·{self._bay(r.task.pickup)}"
        return f"Deliver @ {self._aisle(r.task.dropoff)}·{self._bay(r.task.dropoff)}"

    # ------------------------------------------------------------------
    def layout(self):
        return {
            "w": self.world.w, "h": self.world.h, "cell": C.CELL,
            "obstacles": self.world.static_obstacle_cells(),
            "pickups": [list(p) for p in self.world.pickups],
            "dropoffs": [list(p) for p in self.world.dropoffs],
            "chargers": [list(p) for p in self.world.chargers],
            "depot": [list(p) for p in self.world.depot],
            "config": self.cfg(),
            "max_robots": C.MAX_ROBOTS, "max_tasks": C.MAX_TASKS,
        }

    def _snapshot(self):
        robots = []
        for r in self.robots:
            robots.append({
                "id": r.id, "name": r.name, "color": r.color,
                "pos": [round(float(r.pos[0]), 3), round(float(r.pos[1]), 3)],
                "cell": list(r.cell),
                "mode": self._mode(r), "phase": r.phase,
                "alive": r.alive, "connected": bool(r.connected),
                "avoiding": bool(r.avoiding),
                "battery": round(float(r.battery), 1),
                "speed_mps": round(r.speed * C.CELL, 2),
                "heartbeat_s": round((self.tick - r.last_progress_tick) * C.DT, 1),
                "task_id": r.task.id if r.task else None,
                "task_label": self._task_label(r),
                "eta_s": self._eta(r),
                "path": [list(p) for p in r.path] if r.phase != "charging" else [],
                "aisle": self._aisle(r.cell), "bay": self._bay(r.cell),
                "util": round(r.moving_ticks / max(1, self.tick), 3),
                "priority": self.priority_order.index(r.id),
            })

        tasks = []
        for t in self.alloc.tasks:
            tasks.append({
                "id": t.id, "status": t.status,
                "assignee": t.assignee,
                "assignee_name": self.robots[t.assignee].name
                if t.assignee is not None else None,
                "pickup": list(t.pickup), "dropoff": list(t.dropoff),
                "rerouted": t.rerouted, "eta_s": self._task_eta(t),
                "blocked": t.status == "blocked",
            })

        comp = self.alloc.completion_ticks()
        modes = [rb["mode"] for rb in robots]
        since_kill = (None if self.dashboard_kill_tick is None
                      else self.tick - self.dashboard_kill_tick)
        kpi = {
            "completed": self.alloc.done_count(),
            "total": len(self.alloc.tasks),
            "active_tasks": sum(1 for t in self.alloc.tasks if t.status == "active"),
            "queued_tasks": sum(1 for t in self.alloc.tasks if t.status == "queued"),
            "blocked_tasks": sum(1 for t in self.alloc.tasks if t.status == "blocked"),
            "avg_completion_s": round(float(np.mean(comp)) * C.DT, 1) if comp else None,
            "conflicts": self.kpi_conflicts,
            "near_miss": self.kpi_near_miss,
            "avoided": self.kpi_avoided,
            "fleet_util": round(float(np.mean(
                [r.moving_ticks / max(1, self.tick) for r in self.robots])), 3),
            "avg_battery": round(float(np.mean([r.battery for r in self.robots])), 1),
            "stuck_robots": sum(1 for r in self.robots
                                if self.stuck_ticks.get(r.id, 0) > C.STUCK_TICKS),
            "deadlock_robot_s": round(self.deadlock_robot_ticks * C.DT, 1),
            "makespan_s": (None if self.makespan_tick is None
                           else round(self.makespan_tick * C.DT, 1)),
            "throughput_per_min": round(
                self.alloc.done_count() / max(1e-9, (
                    self.makespan_tick or self.tick) * C.DT / 60.0), 2),
            "detour_count": self.detour_events,
            "detour_extra_m": round(self.detour_extra_cells * C.CELL, 1),
            "detour_extra_pct": round(
                self.detour_extra_cells / max(1e-9, self.dist_travelled_cells) * 100, 1),
            "count": {m: modes.count(m) for m in
                      ("active", "waiting", "rerouting", "charging",
                       "idle", "parked", "error", "comms-lost", "stranded")},
        }

        n_conn = sum(1 for r in self.robots if r.alive and r.connected)
        activity = {
            "astar_replans": self._activity["astar_replans"],
            "astar_replans_tick": self._activity["astar_replans_tick"],
            "pibt_pushes_tick": self._activity["pibt_pushes_tick"],
            "avoiding_now": self._activity["avoiding_now"],
            "connected": n_conn,
            "in_dead_zone": sum(1 for r in self.robots
                                if r.alive and not r.connected),
            "priority_order": [self.robots[i].name for i in self.priority_order],
            "last_auction": self.alloc.log[-1] if self.alloc.log else "—",
        }

        return {
            "tick": self.tick, "sim_time_s": round(self.tick * C.DT, 1),
            "robots": robots, "tasks": tasks, "kpi": kpi, "activity": activity,
            "obstacles": list(self.world.dynamic_obstacles),
            "dead_zones": [list(z) for z in self.comms.dead_zones],
            "dashboard": self.dashboard_online, "since_kill": since_kill,
            "note": self.events_note,
            "events": self.event_log[-14:],
            # legacy keys kept so render.py can consume snapshots unchanged
            "done": self.alloc.done_count(), "total": len(self.alloc.tasks),
            "log": [e["msg"] for e in self.event_log[-4:]],
        }

    # ------------------------------------------------------------------
    def run(self, ticks):
        trailing = 0
        for _ in range(ticks):
            self.step()
            if self.alloc.done_count() == len(self.alloc.tasks) and self.tick > 60:
                trailing += 1
                if trailing > 50:
                    break
        return self.snapshots
