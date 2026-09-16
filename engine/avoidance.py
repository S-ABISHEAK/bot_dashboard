"""Layer 3 - continuous reciprocal collision avoidance: **NH-ORCA**
(Alonso-Mora et al. 2013, over ORCA - van den Berg et al. 2011).

The core solver is `algcore/nh_orca.py`: for every neighbouring robot it builds
one ORCA half-plane on this robot's velocity (each side takes half the
correction), adds full-responsibility half-planes for nearby static cells
(walls / racks / dropped boxes), then solves the 2-D linear program for the
velocity closest to the one MD-PIBT asked for - with the 3-D fallback that
minimises the worst constraint violation when the half-planes are jointly
infeasible.  Each robot's radius is inflated by a tracking-error bound `eps`
(the NH extension) so the holonomic guarantee carries to a real diff-drive base.

The documented ORCA freeze (two robots face-to-face) is still handled upstream
in simulation.py by the stall -> lateral-kick logic.
"""
import numpy as np

from . import config as C
from .algcore.nh_orca import Agent, Line, orca_velocity, _orca_halfplane

_ZERO = np.zeros(2)
_TAU_ROBOT = 2.0
_TAU_STATIC = 1.0
_DT = C.DT
_CELL_RADIUS = 0.16


def _static_line(pos, vel, r_self, cell, dt):
    cpos = np.array([cell[0] + 0.5, cell[1] + 0.5], float)
    ln = _orca_halfplane(pos, vel, r_self, cpos, _ZERO, _CELL_RADIUS,
                         _TAU_STATIC, dt)
    # full responsibility for a static obstacle (drop the reciprocal 0.5)
    return Line(2.0 * ln.point - np.asarray(vel, float), ln.direction)


def choose_velocity(pos, vel, pref_v, max_speed, neighbours, static_cells):
    """neighbours: list of (pos ndarray, vel ndarray). static_cells: list of (x,y)."""
    pos = np.asarray(pos, float)
    vel = np.asarray(vel, float)
    pref_v = np.asarray(pref_v, float)
    eps = C.AVOID_MARGIN
    r_self = C.ROBOT_RADIUS

    me = Agent(pos, radius=r_self, max_speed=max_speed, vel=vel,
               pref_v=pref_v, eps=eps)
    nbrs = []
    for (npos, nvel) in neighbours:
        npos = np.asarray(npos, float)
        if np.hypot(*(npos - pos)) > C.AVOID_HORIZON + 3.0:
            continue
        nbrs.append(Agent(npos, radius=r_self, max_speed=max_speed,
                          vel=np.asarray(nvel, float), eps=eps))

    lines = []
    for cell in static_cells:
        try:
            lines.append(_static_line(pos, vel, r_self + eps, cell, _DT))
        except (ZeroDivisionError, FloatingPointError):
            continue

    try:
        v = orca_velocity(me, nbrs, tau=_TAU_ROBOT, dt=_DT,
                          obstacle_lines=lines or None)
        v = np.asarray(v, float)
        if not np.all(np.isfinite(v)):
            return pref_v
        n = float(np.hypot(*v))
        if n > max_speed:
            v = v / n * max_speed
        return v
    except Exception:
        return pref_v
