"""
NH-ORCA  —  non-holonomic optimal reciprocal collision avoidance
            (Alonso-Mora, Breitenmoser, Rufli, Beardsley, Siegwart, 2013),
            built on ORCA (van den Berg, Guy, Lin, Manocha, 2011).

Working
    ORCA: for each nearby robot the set of relative velocities that lead to a
    collision within time tau is a truncated velocity obstacle.  Each robot
    takes half the responsibility for avoiding it, giving one linear
    half-plane constraint per neighbour on the robot's own velocity.  A small
    2-D linear program then picks the velocity closest to the robot's preferred
    velocity that satisfies every half-plane (with a 3-D fallback that minimises
    the worst constraint violation when the half-planes are jointly
    infeasible).  Because both robots run the same computation, no explicit
    communication or negotiation is needed and the result is collision-free and
    oscillation-free.
    NH extension: a differential-drive robot cannot track an arbitrary
    holonomic velocity exactly.  It is allowed to lag its holonomic reference by
    at most a bounded tracking error eps; inflating every robot's radius by eps
    makes the holonomic ORCA guarantee carry over to the real non-holonomic
    robot.  holo_to_diff() maps the chosen holonomic velocity to wheel commands
    (v, omega).

Use
    The Layer-3 reactive layer: last-metre, high-rate collision avoidance
    between robots (and, with static obstacle lines, walls) that the grid
    planner and MAPF coordinator do not resolve at continuous scale.  Runs
    locally on each robot from neighbour positions/velocities only.
"""
import numpy as np

EPS = 1e-10


def _det(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _norm(v):
    return float(np.hypot(v[0], v[1]))


class Line:
    __slots__ = ("point", "direction")

    def __init__(self, point, direction):
        self.point = np.asarray(point, dtype=float)
        self.direction = np.asarray(direction, dtype=float)


class Agent:
    def __init__(self, pos, radius, max_speed, vel=(0.0, 0.0),
                 pref_v=(0.0, 0.0), eps=0.0):
        self.pos = np.asarray(pos, dtype=float)
        self.vel = np.asarray(vel, dtype=float)
        self.radius = float(radius)
        self.max_speed = float(max_speed)
        self.pref_v = np.asarray(pref_v, dtype=float)
        self.eps = float(eps)               # non-holonomic tracking-error bound


# -- ORCA linear program (RVO2 formulation) ---------------------------
def _lp1(lines, i, radius, opt_v, dir_opt, result):
    d = lines[i]
    dot = float(np.dot(d.point, d.direction))
    disc = dot * dot + radius * radius - float(np.dot(d.point, d.point))
    if disc < 0.0:
        return False, result
    sq = disc ** 0.5
    t_left, t_right = -dot - sq, -dot + sq
    for j in range(i):
        denom = _det(d.direction, lines[j].direction)
        numer = _det(lines[j].direction, d.point - lines[j].point)
        if abs(denom) <= EPS:
            if numer < 0.0:
                return False, result
            continue
        t = numer / denom
        if denom >= 0.0:
            t_right = min(t_right, t)
        else:
            t_left = max(t_left, t)
        if t_left > t_right:
            return False, result
    if dir_opt:
        if float(np.dot(opt_v, d.direction)) > 0.0:
            result = d.point + t_right * d.direction
        else:
            result = d.point + t_left * d.direction
    else:
        t = float(np.dot(d.direction, opt_v - d.point))
        t = min(max(t, t_left), t_right)
        result = d.point + t * d.direction
    return True, result


def _lp2(lines, radius, opt_v, dir_opt, result):
    if dir_opt:
        result = opt_v * radius
    elif float(np.dot(opt_v, opt_v)) > radius * radius:
        result = opt_v / _norm(opt_v) * radius
    else:
        result = np.array(opt_v, dtype=float)
    for i in range(len(lines)):
        if _det(lines[i].direction, lines[i].point - result) > 0.0:
            tmp = result.copy()
            ok, result = _lp1(lines, i, radius, opt_v, dir_opt, result)
            if not ok:
                return i, tmp
    return len(lines), result


def _lp3(lines, n_obst, begin, radius, result):
    distance = 0.0
    for i in range(begin, len(lines)):
        if _det(lines[i].direction, lines[i].point - result) <= distance:
            continue
        proj = list(lines[:n_obst])
        for j in range(n_obst, i):
            det = _det(lines[i].direction, lines[j].direction)
            if abs(det) <= EPS:
                if float(np.dot(lines[i].direction, lines[j].direction)) > 0.0:
                    continue
                point = 0.5 * (lines[i].point + lines[j].point)
            else:
                point = lines[i].point + (
                    _det(lines[j].direction, lines[i].point - lines[j].point) / det
                ) * lines[i].direction
            direction = lines[j].direction - lines[i].direction
            direction = direction / _norm(direction)
            proj.append(Line(point, direction))
        tmp = result.copy()
        opt = np.array([-lines[i].direction[1], lines[i].direction[0]])
        num, result = _lp2(proj, radius, opt, True, result)
        if num < len(proj):
            result = tmp
        distance = _det(lines[i].direction, lines[i].point - result)
    return result


def _orca_halfplane(a_pos, a_vel, a_rad, b_pos, b_vel, b_rad, tau, dt):
    rel_pos = np.asarray(b_pos, float) - np.asarray(a_pos, float)
    rel_vel = np.asarray(a_vel, float) - np.asarray(b_vel, float)
    dist_sq = float(np.dot(rel_pos, rel_pos))
    r = a_rad + b_rad
    r_sq = r * r
    inv_tau = 1.0 / tau
    if dist_sq > r_sq:
        w = rel_vel - inv_tau * rel_pos
        w_sq = float(np.dot(w, w))
        dot = float(np.dot(w, rel_pos))
        if dot < 0.0 and dot * dot > r_sq * w_sq:
            w_len = w_sq ** 0.5
            unit_w = w / w_len
            direction = np.array([unit_w[1], -unit_w[0]])
            u = (r * inv_tau - w_len) * unit_w
        else:
            leg = (dist_sq - r_sq) ** 0.5
            if _det(rel_pos, w) > 0.0:
                direction = np.array([rel_pos[0] * leg - rel_pos[1] * r,
                                      rel_pos[0] * r + rel_pos[1] * leg]) / dist_sq
            else:
                direction = -np.array([rel_pos[0] * leg + rel_pos[1] * r,
                                       -rel_pos[0] * r + rel_pos[1] * leg]) / dist_sq
            u = float(np.dot(rel_vel, direction)) * direction - rel_vel
    else:
        inv_dt = 1.0 / dt
        w = rel_vel - inv_dt * rel_pos
        w_len = _norm(w)
        unit_w = w / w_len
        direction = np.array([unit_w[1], -unit_w[0]])
        u = (r * inv_dt - w_len) * unit_w
    return Line(np.asarray(a_vel, float) + 0.5 * u, direction)


def orca_velocity(agent, neighbours, tau=2.0, dt=0.1, obstacle_lines=None):
    """Chosen holonomic velocity for `agent` given a list of neighbour Agents."""
    lines = list(obstacle_lines or [])
    n_obst = len(lines)
    for nb in neighbours:
        lines.append(_orca_halfplane(agent.pos, agent.vel, agent.radius + agent.eps,
                                     nb.pos, nb.vel, nb.radius + nb.eps, tau, dt))
    result = np.array(agent.pref_v, dtype=float)
    fail, result = _lp2(lines, agent.max_speed, agent.pref_v, False, result)
    if fail < len(lines):
        result = _lp3(lines, n_obst, fail, agent.max_speed, result)
    return result


def holo_to_diff(v_des, theta, v_max, w_max, k_w=1.0):
    """Map a desired holonomic velocity to differential-drive (v, omega) given
    the robot's own speed / turn-rate limits and a heading-control gain."""
    speed = _norm(v_des)
    if speed < EPS:
        return 0.0, 0.0
    heading = np.arctan2(v_des[1], v_des[0])
    err = np.arctan2(np.sin(heading - theta), np.cos(heading - theta))
    v = float(np.clip(speed * np.cos(err), 0.0, v_max))
    w = float(np.clip(k_w * err, -w_max, w_max))
    return v, w


# ------------------------------------------------------------------
if __name__ == "__main__":
    import math

    def run(agents, goals, steps, dt, tau=2.0):
        rng = np.random.default_rng(0)
        min_gap = math.inf
        for _ in range(steps):
            for a, g in zip(agents, goals):
                to_goal = np.asarray(g, float) - a.pos
                d = _norm(to_goal)
                a.pref_v = (to_goal / d * a.max_speed) if d > EPS else np.zeros(2)
                # practical deadlock-breaker: a small preferred-velocity rotation
                # when a robot is stuck far from its goal (RVO2 demos do the same)
                if d > 10 * a.radius and _norm(a.vel) < 0.15 * a.max_speed:
                    ang = rng.uniform(-0.6, 0.6)
                    ca, sa = math.cos(ang), math.sin(ang)
                    a.pref_v = np.array([ca * a.pref_v[0] - sa * a.pref_v[1],
                                         sa * a.pref_v[0] + ca * a.pref_v[1]])
            nv = [orca_velocity(a, [o for o in agents if o is not a], tau=tau, dt=dt)
                  for a in agents]
            for a, v in zip(agents, nv):
                a.vel = v
                a.pos = a.pos + v * dt
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    min_gap = min(min_gap, _norm(agents[i].pos - agents[j].pos))
        reached = all(_norm(np.asarray(g, float) - a.pos) < 3 * a.radius
                      for a, g in zip(agents, goals))
        return min_gap, reached

    R, V = 0.3, 1.0

    a = Agent((-4.0, 0.0), radius=R, max_speed=V, eps=0.02)
    b = Agent((4.0, 0.03), radius=R, max_speed=V, eps=0.02)
    gap, reached = run([a, b], [(4.0, 0.0), (-4.0, 0.03)], steps=600, dt=0.05)
    assert gap >= 2 * R - 1e-3 and reached
    print(f"head-on pair     : min gap {gap:.3f} (>= {2 * R:.2f}), both arrived")

    n = 6
    ags = [Agent((4 * math.cos(2 * math.pi * k / n + 0.05),
                  4 * math.sin(2 * math.pi * k / n + 0.05)),
                 radius=R, max_speed=V, eps=0.02) for k in range(n)]
    gls = [(-p.pos[0], -p.pos[1]) for p in ags]
    gap, reached = run(ags, gls, steps=900, dt=0.05)
    assert gap >= 2 * R - 1e-3 and reached
    print(f"antipodal circle : min gap {gap:.3f} (>= {2 * R:.2f}), all {n} crossed")

    v, w = holo_to_diff(np.array([0.0, 1.0]), theta=0.0, v_max=1.0, w_max=3.0)
    assert w > 1.0 and v >= 0.0
    print(f"holo->diff       : v_des=(0,1), theta=0  ->  v={v:.2f}, w={w:.2f}")
    print("OK")
