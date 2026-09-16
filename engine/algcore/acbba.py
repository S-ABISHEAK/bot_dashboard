"""
ACBBA  —  Asynchronous Consensus-Based Bundle Algorithm
          (Johnson, Ponda, Choi, How), an asynchronous variant of CBBA
          (Choi, Brunet, How, 2009).

Working
    Distributed task allocation with no auctioneer.  Two phases, run repeatedly:
      1. Bundle build — each agent greedily appends the task giving the largest
         marginal increase to its own score, as long as its bid beats the best
         bid it currently knows for that task.  The marginal-score function is
         supplied by the caller; if it is submodular (diminishing marginal gain)
         CBBA is guaranteed to converge.
      2. Consensus — agents exchange, per task, the current winning bid y[j],
         winning agent z[j] and an information-timestamp vector s[k].  The CBBA
         action table (update / reset / leave) decides whose information wins;
         the timestamp vector makes out-of-order / asynchronous messages resolve
         deterministically (the "A" in ACBBA).  A task lost in consensus is
         released together with every task added after it, then the bundle is
         rebuilt.
    Converges to a conflict-free assignment (each task has at most one winner)
    within 50% of optimal for submodular scores.

Use
    The Layer-4 task-allocation layer: which robot services which job.  Fully
    peer-to-peer over the comm graph, tolerant of dropped / partitioned robots
    (their tasks are re-won), event-triggered rather than round-synchronised.

API
    ACBBAAgent(agent_id, task_ids, marginal_fn, neighbours, max_bundle)
        marginal_fn(path, task) -> (gain, insert_position)
            the best marginal score of adding `task` to the ordered `path`,
            and the position at which to insert it.
"""

NO_ONE = -1


class ACBBAAgent:
    def __init__(self, agent_id, task_ids, marginal_fn, neighbours, max_bundle):
        self.id = agent_id
        self.tasks = list(task_ids)
        self.marginal = marginal_fn
        self.neighbours = list(neighbours)
        self.L = int(max_bundle)
        self.alive = True

        self.bundle = []                       # tasks in the order added
        self.path = []                         # tasks in service order
        self.y = {j: 0.0 for j in self.tasks}          # best known bid per task
        self.z = {j: NO_ONE for j in self.tasks}       # best known winner per task
        self.s = {}                            # timestamp of last info about agent k

    # -- phase 1 --------------------------------------------------
    def build_bundle(self, time):
        while len(self.bundle) < self.L:
            best_j, best_c, best_pos = None, 0.0, 0
            for j in self.tasks:
                if j in self.bundle:
                    continue
                c, pos = self.marginal(self.path, j)
                if c > self.y[j] + 1e-9 and c > best_c + 1e-9:
                    best_j, best_c, best_pos = j, c, pos
            if best_j is None:
                break
            self.bundle.append(best_j)
            self.path.insert(best_pos, best_j)
            self.y[best_j] = best_c
            self.z[best_j] = self.id
            self.s[self.id] = time

    # -- phase 2 --------------------------------------------------
    def receive(self, msg, time):
        k = msg["from"]
        yk, zk, sk = msg["y"], msg["z"], msg["s"]
        s_old = dict(self.s)                   # rules compare against pre-update stamps

        released_from = None
        for j in self.tasks:
            act = _rule(self.id, k, self.z[j], zk[j],
                        self.y[j], yk[j], s_old, sk)
            if act == "update":
                self.y[j], self.z[j] = yk[j], zk[j]
            elif act == "reset":
                self.y[j], self.z[j] = 0.0, NO_ONE
            if self.z[j] != self.id and j in self.bundle:
                idx = self.bundle.index(j)
                released_from = idx if released_from is None else min(released_from, idx)

        if released_from is not None:
            for j in self.bundle[released_from + 1:]:
                if self.z[j] == self.id:
                    self.y[j], self.z[j] = 0.0, NO_ONE
            dropped = set(self.bundle[released_from:])
            self.bundle = self.bundle[:released_from]
            self.path = [t for t in self.path if t not in dropped]

        self.s[k] = time
        for m, tsm in sk.items():
            self.s[m] = max(self.s.get(m, 0), tsm)
        self.build_bundle(time)

    def message(self):
        return {"from": self.id, "y": dict(self.y), "z": dict(self.z), "s": dict(self.s)}


def _rule(i, k, zij, zkj, yij, ykj, si, sk):
    EPS = 1e-9

    def newer(m):
        return sk.get(m, 0) > si.get(m, 0) + EPS

    if zkj == k:
        if zij == i:
            return "update" if ykj > yij + EPS else "leave"
        if zij == k:
            return "update"
        if zij != NO_ONE:
            return "update" if (newer(zij) or ykj > yij + EPS) else "leave"
        return "update"
    if zkj == i:
        if zij == i:
            return "leave"
        if zij == k:
            return "reset"
        if zij != NO_ONE:
            return "reset" if newer(zij) else "leave"
        return "leave"
    if zkj != NO_ONE:
        m = zkj
        if zij == i:
            return "update" if (newer(m) and ykj > yij + EPS) else "leave"
        if zij == k:
            return "update" if newer(m) else "reset"
        if zij == m:
            return "update" if newer(m) else "leave"
        if zij != NO_ONE:
            if newer(m) and sk.get(zij, 0) > si.get(zij, 0) + EPS:
                return "update"
            if newer(m) and ykj > yij + EPS:
                return "update"
            return "leave"
        return "update" if newer(m) else "leave"
    # zkj == NO_ONE
    if zij == i:
        return "leave"
    if zij == k:
        return "update"
    if zij != NO_ONE:
        return "update" if newer(zij) else "leave"
    return "leave"


def run_to_consensus(agents, max_rounds=1000):
    """Synchronous driver: round-robin message passing until the winner/bid
    tables stop changing for longer than the graph diameter."""
    by_id = {a.id: a for a in agents}
    quiet = 0
    for t in range(1, max_rounds + 1):
        for a in agents:
            if a.alive:
                a.build_bundle(t)
        changed = False
        for a in agents:
            if not a.alive:
                continue
            for k in a.neighbours:
                nb = by_id.get(k)
                if nb is None or not nb.alive:
                    continue
                before = (dict(a.y), dict(a.z))
                a.receive(nb.message(), t)
                if (a.y, a.z) != before:
                    changed = True
        quiet = 0 if changed else quiet + 1
        if quiet > len(agents):
            return t
    return max_rounds


def assignment(agents):
    out = {}
    for a in agents:
        if a.alive:
            for j in a.bundle:
                out[j] = a.id
    return out


# ------------------------------------------------------------------
if __name__ == "__main__":
    import numpy as np

    # example score: time-discounted reward for a spatial pickup tour
    rng = np.random.default_rng(4)
    n_agents, n_tasks, cap = 4, 9, 3
    DISCOUNT = 0.95
    homes = rng.uniform(0, 10, size=(n_agents, 2))
    tpos = {j: rng.uniform(0, 10, size=2) for j in range(n_tasks)}
    reward = {j: 100.0 for j in range(n_tasks)}

    def make_marginal(home):
        def score(path):
            total, dist, prev = 0.0, 0.0, home
            for j in path:
                dist += float(np.hypot(*(tpos[j] - prev)))
                total += reward[j] * (DISCOUNT ** dist)
                prev = tpos[j]
            return total

        def marginal(path, task):
            base = score(path)
            best, best_pos = -np.inf, 0
            for pos in range(len(path) + 1):
                g = score(path[:pos] + [task] + path[pos:]) - base
                if g > best:
                    best, best_pos = g, pos
            return best, best_pos
        return marginal

    ring = {i: [(i - 1) % n_agents, (i + 1) % n_agents] for i in range(n_agents)}
    agents = [ACBBAAgent(i, range(n_tasks), make_marginal(homes[i]), ring[i], cap)
              for i in range(n_agents)]

    rounds = run_to_consensus(agents)
    asn = assignment(agents)
    counts = {}
    for a in agents:
        for j in a.bundle:
            counts[j] = counts.get(j, 0) + 1
    assert all(v == 1 for v in counts.values()), f"task double-booked: {counts}"
    for a in agents:
        assert a.z == agents[0].z, "agents disagree on winners"
    print(f"4 agents / 9 tasks : consensus in {rounds} rounds, "
          f"{len(asn)}/{n_tasks} tasks assigned")
    for a in agents:
        print(f"   agent {a.id}: bundle {list(a.bundle)}")

    victim = max(agents, key=lambda a: len(a.bundle))
    lost = list(victim.bundle)
    victim.alive = False
    for a in agents:
        if a is not victim:
            for j in lost:
                a.y[j], a.z[j] = 0.0, NO_ONE
    run_to_consensus([a for a in agents if a.alive])
    asn2 = assignment(agents)
    assert all(j in asn2 for j in lost), f"tasks {lost} not re-won"
    print(f"agent {victim.id} dropped   : its tasks {lost} re-won by "
          f"{sorted(set(asn2[j] for j in lost))}")
    print("OK")
