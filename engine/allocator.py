"""Layer 4 - decentralised task allocation: **ACBBA / CBBA**
(Johnson et al.; Choi, Brunet, How 2009).  Core in `algcore/acbba.py`.

Each open auction runs the real two-phase algorithm over the currently idle
robots and unassigned tasks:

  1. bundle build  - every robot greedily appends the task with the largest
     marginal increase to its time-discounted tour score (a submodular score,
     so CBBA is guaranteed to converge);
  2. consensus     - robots exchange, per task, the winning bid / winner /
     information-timestamp vector and apply the CBBA action table until the
     winner assignment stops changing.

The result is conflict-free (each task has at most one winner).  A task whose
assignee later fails, loses comms, or diverts to charge is re-opened here and
re-won in the next auction (dropped-robot tolerance).  Bundle length is 1 for
the live console because each robot services one job at a time.
"""
from .algcore.acbba import ACBBAAgent, run_to_consensus

_REWARD = 100.0
_DISCOUNT = 0.97
_MAX_BUNDLE = 1


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class Task:
    __slots__ = ("id", "pickup", "dropoff", "status", "assignee",
                 "assigned_tick", "done_tick", "rerouted", "fail_count")

    def __init__(self, tid, pickup, dropoff):
        self.id = tid
        self.pickup = tuple(pickup)
        self.dropoff = tuple(dropoff)
        self.status = "queued"            # queued | active | done | blocked
        self.assignee = None
        self.assigned_tick = -1
        self.done_tick = -1
        self.rerouted = False
        self.fail_count = 0


class Allocator:
    def __init__(self, tasks):
        self.tasks = tasks
        self.by_id = {t.id: t for t in tasks}
        self.log = []

    def open_tasks(self):
        return [t for t in self.tasks if t.status == "queued"]

    def done_count(self):
        return sum(1 for t in self.tasks if t.status == "done")

    def completion_ticks(self):
        return [t.done_tick - t.assigned_tick
                for t in self.tasks if t.status == "done" and t.assigned_tick >= 0]

    def reopen(self, robot_id, reason, tick):
        for t in self.tasks:
            if t.status == "active" and t.assignee == robot_id:
                t.status = "queued"
                t.assignee = None
                self.log.append(f"t{tick}: task {t.id} re-opened ({reason})")

    # ------------------------------------------------------------------
    def _marginal_fn(self, home, open_ids):
        pos = {j: self.by_id[j].pickup for j in open_ids}
        drop = {j: self.by_id[j].dropoff for j in open_ids}

        def tour_cost(path):
            total, prev = 0.0, home
            for j in path:
                total += _manhattan(prev, pos[j])
                total += _manhattan(pos[j], drop[j])
                prev = drop[j]
            return total

        def score(path):
            s, prev, dist = 0.0, home, 0.0
            for j in path:
                dist += _manhattan(prev, pos[j]) + _manhattan(pos[j], drop[j])
                s += _REWARD * (_DISCOUNT ** dist)
                prev = drop[j]
            return s

        def marginal(path, task):
            base = score(path)
            best, best_pos = -1e18, len(path)
            for p in range(len(path) + 1):
                g = score(path[:p] + [task] + path[p:]) - base
                if g > best:
                    best, best_pos = g, p
            return best, best_pos

        return marginal

    def auction(self, robots, dist_to, tick):
        """robots: robot objects.  dist_to(robot, cell) -> float (unused here;
        kept for signature compatibility).  Only genuinely idle robots bid."""
        idle = [r for r in robots
                if r.alive and r.task is None and r.phase == "idle"]
        open_ids = [t.id for t in self.open_tasks()]
        if not idle or not open_ids:
            return

        n = len(idle)
        if n <= 2:
            graph = {i: [k for k in range(n) if k != i] for i in range(n)}
        else:
            graph = {i: [(i - 1) % n, (i + 1) % n] for i in range(n)}

        agents = [
            ACBBAAgent(i, open_ids, self._marginal_fn(idle[i].cell, open_ids),
                       graph[i], _MAX_BUNDLE)
            for i in range(n)
        ]
        run_to_consensus(agents)

        for i, ag in enumerate(agents):
            if not ag.bundle:
                continue
            j = ag.bundle[0]
            t = self.by_id[j]
            if t.status != "queued":
                continue
            winner = idle[i]
            t.status = "active"
            t.assignee = winner.id
            t.assigned_tick = tick
            winner.assign_task(t)
            winner.last_progress_tick = tick        # fresh heartbeat window
            self.log.append(
                f"t{tick}: task {t.id} -> {winner.name} (ACBBA bid {ag.y[j]:.0f})")
