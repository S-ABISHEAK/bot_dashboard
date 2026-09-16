"""
Mesh pub/sub  —  router-mediated publish/subscribe over a mobile mesh
                 (the Zenoh model: routers + peers, key-expression routing).

Working
    Peers (robots) open a session to a router and declare publishers /
    subscribers on slash-separated key expressions ("fleet/amr3/pose"), with
    "*" matching one token and "**" matching any number.  Subscriptions are
    flooded once through the router graph so every router learns which
    direction leads to an interested subscriber.  A put() is then forwarded
    only along routers that have a matching downstream subscription and is
    delivered to each matching local subscriber exactly once — no full-mesh
    flooding.  Because discovery is mediated by the router backbone, the number
    of connections a peer maintains is O(1) and the fleet-wide connection count
    is O(n), versus O(n^2) for a peer-to-peer full mesh (the property that lets
    the fleet's comms scale as robots are added).

Use
    The Layer-5 transport model: how robots share pose / intent / bids /
    heartbeats without every robot connecting to every other robot, and the
    place a partition / dead-zone fallback would hook in (a peer whose router
    link drops falls back to last-known state + local sensing).
"""
import numpy as np


def key_match(pattern, key):
    return _m(pattern.split("/"), key.split("/"))


def _m(ps, ks):
    if not ps:
        return not ks
    if ps[0] == "**":
        return _m(ps[1:], ks) or (bool(ks) and _m(ps, ks[1:]))
    if not ks:
        return False
    if ps[0] == "*" or ps[0] == ks[0]:
        return _m(ps[1:], ks[1:])
    return False


class Router:
    def __init__(self, name):
        self.name = name
        self.neighbours = {}                       # name -> Router
        self.table = {}                            # key_expr -> set(hop)  (Session | Router)

    def link(self, other):
        self.neighbours[other.name] = other
        other.neighbours[self.name] = self

    def _declare(self, key, hop, came_from=None):
        s = self.table.setdefault(key, set())
        if hop in s:
            return
        s.add(hop)
        for r in self.neighbours.values():
            if r is not came_from:
                r._declare(key, self, came_from=self)

    def publish(self, key, value):
        stats = {"routers": set(), "subscribers": []}
        self._route(key, value, stats, seen_r=set(), seen_s=set())
        return stats

    def _route(self, key, value, stats, seen_r, seen_s):
        seen_r.add(self.name)
        stats["routers"].add(self.name)
        for pattern, hops in list(self.table.items()):
            if not key_match(pattern, key):
                continue
            for hop in hops:
                if isinstance(hop, Session):
                    if hop.name not in seen_s:
                        seen_s.add(hop.name)
                        hop._deliver(key, value)
                        stats["subscribers"].append(hop.name)
                elif hop.name not in seen_r:
                    hop._route(key, value, stats, seen_r, seen_s)


class Session:
    _count = 0

    def __init__(self, router, name=None):
        Session._count += 1
        self.name = name or f"peer{Session._count}"
        self.router = router
        self.subs = []                            # (key, callback)
        self.inbox = []

    def declare_publisher(self, key):
        return _Publisher(self, key)

    def declare_subscriber(self, key, callback=None):
        self.subs.append((key, callback))
        self.router._declare(key, self)

    def put(self, key, value):
        return self.router.publish(key, value)

    def _deliver(self, key, value):
        cbs = [cb for k, cb in self.subs if key_match(k, key)]
        if cbs:
            self.inbox.append((key, value))
            for cb in cbs:
                if cb:
                    cb(key, value)


class _Publisher:
    def __init__(self, session, key):
        self.session, self.key = session, key

    def put(self, value):
        return self.session.put(self.key, value)


def connection_scaling(n_peers, n_routers):
    """Connections maintained fleet-wide: router-mediated vs peer-to-peer mesh."""
    full_mesh = n_peers * (n_peers - 1) // 2
    brokered = n_peers + max(0, n_routers - 1)     # one link per peer + router backbone
    return full_mesh, brokered


# ------------------------------------------------------------------
if __name__ == "__main__":
    # 3 routers in a line: R0 -- R1 -- R2
    R = [Router(f"R{i}") for i in range(3)]
    R[0].link(R[1])
    R[1].link(R[2])

    hits = []
    s1 = Session(R[0], "amr1")
    s2 = Session(R[0], "amr2")
    s3 = Session(R[1], "dash")
    s4 = Session(R[2], "amr4")
    s5 = Session(R[2], "amr5")

    for s in (s1, s2, s4, s5):
        s.declare_subscriber("fleet/*/pose", lambda k, v, n=s.name: hits.append(n))
    s3.declare_subscriber("fleet/*/telemetry")          # dash wants telemetry, not pose

    stats = Session(R[2], "amr3").declare_publisher("fleet/amr3/pose").put({"x": 4.0, "y": 1.0})

    got = sorted(stats["subscribers"])
    assert got == ["amr1", "amr2", "amr4", "amr5"], got
    assert "dash" not in got, "dash subscribed to telemetry, must not receive pose"
    assert stats["routers"] == {"R0", "R1", "R2"}, stats["routers"]
    print(f"pub fleet/amr3/pose from R2 -> delivered to {got}")
    print(f"                            crossed routers {sorted(stats['routers'])}")

    # wildcard depth
    Session(R[0], "logger").declare_subscriber("fleet/**")
    s = Session(R[0]).declare_publisher("fleet/zone/a/amr7/battery").put(0.42)
    assert "logger" in s["subscribers"]
    print("pub fleet/zone/a/amr7/battery -> matched 'fleet/**' subscriber")

    # connection scaling
    for n in (4, 8, 16, 32):
        mesh, brokered = connection_scaling(n, n_routers=3)
        print(f"  {n:2d} robots : peer-to-peer mesh {mesh:4d} links   router-mediated {brokered:3d} links")
    m32, b32 = connection_scaling(32, 3)
    assert b32 * 4 < m32, "router-mediated must scale far better than full mesh"
    print("OK")
