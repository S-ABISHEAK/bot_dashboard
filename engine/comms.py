"""Layer 5 - fleet comms, modelled on the **Zenoh pub/sub mesh**
(`algcore/mesh_pubsub.py`: routers + peer sessions, key-expression routing).

Three routers form the warehouse backbone (R0-R1-R2).  Each robot opens a
session, declares a publisher on `fleet/<id>/pose` and a subscriber on
`fleet/*/pose`; pose updates are routed through the backbone to every other
robot's session - O(n) links, not O(n^2).

On top of the transport we model rectangular Wi-Fi dead zones: a robot inside
one cannot put to the mesh (its pose goes stale for everyone else) and receives
nothing fleet-wide, so it falls back to CONNECTIVITY_LOST behaviour - local
sensing within SENSE_RADIUS and reduced speed.
"""
import numpy as np

from . import config as C
from .algcore.mesh_pubsub import Router, Session


class CommsBus:
    def __init__(self):
        self.dead_zones = []               # list of (x, y, w, h) in cells
        self.latest = {}                   # robot_id -> (pos, vel, tick)

        self._routers = [Router("R0"), Router("R1"), Router("R2")]
        self._routers[0].link(self._routers[1])
        self._routers[1].link(self._routers[2])
        self._sessions = {}                # robot_id -> Session

    # ------------------------------------------------------------------
    def add_dead_zone(self, rect):
        self.dead_zones.append(tuple(rect))

    def clear_dead_zones(self):
        self.dead_zones = []

    def in_dead_zone(self, pos):
        for (x, y, w, h) in self.dead_zones:
            if x <= pos[0] <= x + w and y <= pos[1] <= y + h:
                return True
        return False

    # ------------------------------------------------------------------
    def _session(self, robot_id, pos):
        s = self._sessions.get(robot_id)
        if s is None:
            third = max(1, C.GRID_W // 3)
            ri = min(2, int(pos[0]) // third)
            s = Session(self._routers[ri], name=f"amr{robot_id}")

            def _cb(_key, value, rid=robot_id):
                pid, ppos, pvel, ptick = value
                if pid != rid:
                    self.latest[pid] = (np.array(ppos, float),
                                        np.array(pvel, float), ptick)

            s.declare_subscriber("fleet/*/pose", _cb)
            s._pub = s.declare_publisher(f"fleet/amr{robot_id}/pose")
            self._sessions[robot_id] = s
        return s

    def publish(self, robot_id, pos, vel, tick):
        if self.in_dead_zone(pos):
            return False                   # message never leaves the robot
        s = self._session(robot_id, pos)
        s._pub.put((robot_id, np.array(pos, float).tolist(),
                    np.array(vel, float).tolist(), tick))
        self.latest[robot_id] = (np.array(pos, float), np.array(vel, float), tick)
        return True

    def neighbours_for(self, robot):
        """What `robot` believes about the others this tick.
        Connected -> fleet-wide shared positions (delivered over the mesh).
        Dead zone -> only robots physically within SENSE_RADIUS."""
        others = []
        connected = not self.in_dead_zone(robot.pos)
        for rid, (pos, vel, _t) in self.latest.items():
            if rid == robot.id:
                continue
            if connected or np.linalg.norm(pos - robot.pos) <= C.SENSE_RADIUS:
                others.append((pos, vel))
        return others, connected
