"""Central configuration for the fleet simulation engine.

Distances are in grid cells (1 cell == CELL metres).  Nothing here needs a GPU.
Robot / task counts are chosen at runtime by the dashboard; the values below are
only defaults and hard caps.
"""

# ----------------------------------------------------------------------
# World
# ----------------------------------------------------------------------
GRID_W = 40
GRID_H = 22
CELL = 0.5                       # metres per cell

# Horizontal shelf blocks: (row_lo, row_hi) pairs spanning x in [SHELF_X0, SHELF_X1)
SHELF_ROWS = [(3, 4), (7, 8), (11, 12), (15, 16)]
SHELF_X0, SHELF_X1 = 5, 35
SHELF_GAPS = (13, 14, 26, 27)   # x columns kept open = 2-wide vertical cross-aisles

# Stations (cell coords) - left pick corridor x=2, right drop corridor x=37
PICKUPS = [(2, y) for y in (2, 5, 9, 13, 17, 20)]
DROPOFFS = [(37, y) for y in (2, 5, 9, 13, 17, 20)]
CHARGERS = [(19, 20), (21, 20)]

# ----------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------
DT = 0.10
TOTAL_TICKS = 1400              # cap for the scripted / headless run

# ----------------------------------------------------------------------
# Robots
# ----------------------------------------------------------------------
MAX_ROBOTS = 6
MAX_TASKS = 20
N_ROBOTS = 4                    # default only
N_TASKS = 8                     # default only

ROBOT_RADIUS = 0.24            # < 0.5 so robots in adjacent cells don't overlap
MAX_SPEED = 2.0                 # cells / s  (~1.0 m/s at CELL=0.5)
CAUTION_SPEED = 0.9            # when comms are down
ROBOT_COLORS = ["#4f8cff", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#14b8a6"]
ROBOT_NAMES = ["AMR-1", "AMR-2", "AMR-3", "AMR-4", "AMR-5", "AMR-6"]
ROBOT_STARTS = [(2, 1), (9, 1), (17, 1), (24, 1), (31, 1), (37, 1)]

# Standby / completion depot - one numbered parking bay per robot, in the open
# hall below the last shelf (row y=18).  Sited well LEFT of the charger bay
# (chargers at x=19,21) so a row of parked robots never walls off the chargers'
# north approach, and clear of the pickup column (x=2).  A jobless robot retires
# to its bay and pulls straight back out when ACBBA gives it a task.
DEPOT = [(x, GRID_H - 4) for x in range(12, 12 + MAX_ROBOTS)]

# ----------------------------------------------------------------------
# Layer 3 - reciprocal collision avoidance (RVO / ORCA-style, sampled)
# ----------------------------------------------------------------------
AVOID_HORIZON = 3.0
AVOID_MARGIN = 0.18
AVOID_WEIGHT = 11.0
SENSE_RADIUS = 3.0
STANDOFF_TICKS = 8
STANDOFF_KICK = 0.9

# ----------------------------------------------------------------------
# Layer 4 - CBBA / ACBBA task auction
# ----------------------------------------------------------------------
REAUCTION_EVERY = 15
HEARTBEAT_TIMEOUT = 130
REPLAN_BACKOFF = 25            # ticks to wait before retrying a failed A* plan
                              # (rate-limited / event-driven planning)

# ----------------------------------------------------------------------
# Layer 2 - PIBT congestion-aware heuristic
# ----------------------------------------------------------------------
# The heat map only breaks ties between cells that do NOT already move the robot
# closer to its goal, and its influence is capped, so it can never outweigh the
# distance-to-goal gradient.  (An earlier uncapped version created a
# self-reinforcing repulsive well that trapped robots in low-traffic corners.)
CONGESTION_DECAY = 0.92
CONGESTION_WEIGHT = 0.6
CONGESTION_CAP = 3.0            # max heat value that counts toward the move cost

# ----------------------------------------------------------------------
# Benchmark / A-B mode (5-layer stack vs. stop-and-wait baseline)
# ----------------------------------------------------------------------
STUCK_TICKS = 20              # consecutive near-zero-speed ticks before a robot
                             # counts as "stuck" for the deadlock metric (2.0 s)
BENCH_TICK_CAP = 4000        # server freezes a benchmark run after this many
                             # ticks (the stop-and-wait baseline may never finish)
SW_OVERRIDE_TICKS = 20       # stop-and-wait: wait-streak before a robot's
                             # priority is overridden (jumps the queue)
SW_DETOUR_TICKS = 35         # stop-and-wait: wait-streak before a reactive
                             # D* Lite detour around a blocking robot

# ----------------------------------------------------------------------
# Battery (behavioural model)
# ----------------------------------------------------------------------
BATTERY_START = (45.0, 100.0)   # uniform range at spawn (staggered)
BATTERY_DRAIN_MOVE = 0.035      # % per tick while driving
BATTERY_DRAIN_IDLE = 0.012      # % per tick while idle
BATTERY_CHARGE_RATE = 0.55      # % per tick on a charger
BATTERY_LOW = 24.0             # divert to charger below this
BATTERY_FULL = 92.0            # leave charger above this

# ----------------------------------------------------------------------
# Scripted event timeline - only used by the standalone video (scripted=True)
# ----------------------------------------------------------------------
EVENTS = {
    150: ("obstacle", (13, 11)),
    320: ("dead_zone", (2, 13, 10, 8)),
    520: ("robot_fail", 2),
    560: ("dashboard_kill", None),
    760: ("dead_zone_clear", None),
    860: ("robot_recover", 2),
}

RANDOM_SEED = 7
