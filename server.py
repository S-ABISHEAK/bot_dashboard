"""FastAPI backend for the FleetNet live dashboard.

Run:  python server.py           (http://127.0.0.1:8000)
or:   uvicorn server:app --reload

The simulation engine (engine/) is the authoritative source of every robot's
motion.  This process just steps it on a timer and streams JSON snapshots to the
browser over a WebSocket; controls arrive as HTTP POSTs.
"""
import asyncio
import contextlib
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from engine import config as C, render
from engine.simulation import Simulation

STATIC = Path(__file__).parent / "static"
VIDEO = STATIC / "fleet_demo.mp4"


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _mk_sims(n_robots, n_tasks, seed):
    return {
        "stack": Simulation(n_robots=n_robots, n_tasks=n_tasks, seed=seed),
        "stopwait": Simulation(n_robots=n_robots, n_tasks=n_tasks, seed=seed,
                               coordination="stopwait"),
    }


class Session:
    """Holds the shared simulation(s) and every connected browser.

    Normally only ``sims["stack"]`` runs.  In benchmark mode both sims are
    stepped in lockstep on an identical scenario so the 5-layer stack can be
    compared against the stop-and-wait baseline."""

    def __init__(self):
        self.sims = _mk_sims(4, 10, 7)
        self.benchmark = False
        self.running = False
        self._settle = 0            # extra ticks run after the last task, so
                                    # finished robots reach their depot bay
        self.speed = 1.0
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()
        self.export_state = {"status": "idle", "pct": 0, "url": None}

    @property
    def sim(self):
        """The primary simulation (stack) — what export / config / layout use."""
        return self.sims["stack"]

    # -- messages ---------------------------------------------------------
    def layout_msg(self):
        return {"type": "layout", "data": self.sim.layout(),
                "speed": self.speed, "running": self.running,
                "benchmark": self.benchmark}

    def frame_msg(self):
        def snap(s):
            return s.snapshots[-1] if s.snapshots else s._snapshot()
        stack = snap(self.sims["stack"])
        stopw = snap(self.sims["stopwait"])
        return {"type": "frame", "data": {
            "stack": stack,
            "stopwait": stopw if self.benchmark else None,
            "cmp": self._scoreboard(stack, stopw) if self.benchmark else None,
        }}

    def _scoreboard(self, a, b):
        ka, kb = a["kpi"], b["kpi"]
        BIG = 10 ** 9
        rows = []

        def row(key, label, va, vb, better, fmt=lambda x: x):
            if better == "context":
                winner = "none"
            elif better == "high":
                winner = ("stack" if va > vb else "stopwait" if vb > va else "tie")
            else:
                winner = ("stack" if va < vb else "stopwait" if vb < va else "tie")
            rows.append({"key": key, "label": label,
                         "stack": fmt(va), "stopwait": fmt(vb),
                         "raw_stack": va, "raw_stopwait": vb,
                         "better": better, "winner": winner})

        row("completed", "Tasks completed", ka["completed"], kb["completed"], "high")
        row("throughput", "Throughput (tasks/min)",
            ka["throughput_per_min"], kb["throughput_per_min"], "high")
        row("makespan", "Makespan (s)",
            ka["makespan_s"] if ka["makespan_s"] is not None else BIG,
            kb["makespan_s"] if kb["makespan_s"] is not None else BIG,
            "low", fmt=lambda x: "—" if x >= BIG else x)
        row("stuck", "Stuck robots (now)",
            ka["stuck_robots"], kb["stuck_robots"], "low")
        row("deadlock", "Deadlock robot-seconds",
            ka["deadlock_robot_s"], kb["deadlock_robot_s"], "low")
        row("detour", "Detour recovery cost",
            f'{ka["detour_extra_m"]} m',
            f'{kb["detour_extra_m"]} m ({kb["detour_extra_pct"]}%)', "context")

        wins = sum(1 for r in rows if r["winner"] == "stack")
        losses = sum(1 for r in rows if r["winner"] == "stopwait")
        return {
            "rows": rows,
            "verdict": ("stack" if wins > losses
                        else "stopwait" if losses > wins else "tie"),
            "score": [wins, losses],
            "tick": a["tick"],
            "capped": a["tick"] >= C.BENCH_TICK_CAP,
        }

    async def broadcast(self, msg):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for d in dead:
            self.clients.discard(d)

    # -- the step loop --------------------------------------------------
    def _all_done(self, s):
        return s.alloc.done_count() == len(s.alloc.tasks)

    @staticmethod
    def _fleet_settled(s):
        return all(r.parked or not r.alive
                   or r.phase in ("charging", "to_charge")
                   for r in s.robots)

    async def loop(self):
        while True:
            if self.running:
                async with self.lock:
                    self.sims["stack"].step()
                    if self.benchmark:
                        self.sims["stopwait"].step()
                    tasks_done = self._all_done(self.sims["stack"]) and (
                        not self.benchmark or self._all_done(self.sims["stopwait"]))
                    # after the last task, keep stepping briefly so finished
                    # robots trundle into their depot bays before we freeze.
                    if tasks_done and not self.benchmark:
                        self._settle += 1
                        done = (self._fleet_settled(self.sims["stack"])
                                or self._settle > 400)
                    else:
                        self._settle = 0
                        done = tasks_done
                    capped = (self.benchmark
                              and self.sims["stack"].tick >= C.BENCH_TICK_CAP)
                await self.broadcast(self.frame_msg())
                if done or capped:
                    self.running = False
                    note = ("Benchmark hit the tick cap — the stop-and-wait "
                            "baseline did not converge."
                            if capped and not done else "All tasks delivered.")
                    await self.broadcast({"type": "status", "running": False,
                                          "note": note})
                await asyncio.sleep(max(0.008, C.DT / self.speed))
            else:
                await asyncio.sleep(0.05)

    # -- actions ------------------------------------------------------
    async def reconfigure(self, n_robots, n_tasks, seed):
        async with self.lock:
            self.sims = _mk_sims(n_robots, n_tasks, seed)
            self.running = False
            self._settle = 0
        await self.broadcast(self.layout_msg())
        await self.broadcast(self.frame_msg())

    async def reset(self):
        cfg = self.sim.cfg()
        await self.reconfigure(cfg["n_robots"], cfg["n_tasks"], cfg["seed"])

    async def export(self):
        if self.export_state["status"] == "running":
            return
        snaps = list(self.sim.snapshots)
        if len(snaps) < 5:
            await self.broadcast({"type": "export", "status": "error",
                                  "msg": "Run the simulation first."})
            return
        self.export_state = {"status": "running", "pct": 0, "url": None}
        world = self.sim.world
        await self.broadcast({"type": "export", "status": "running", "pct": 0,
                              "frames": len(snaps)})

        loop = asyncio.get_running_loop()

        def _prog(i, tot):
            pct = int(i / tot * 100)
            if pct != self.export_state["pct"]:
                self.export_state["pct"] = pct
                asyncio.run_coroutine_threadsafe(
                    self.broadcast({"type": "export", "status": "running", "pct": pct}),
                    loop)

        def _job():
            render.animate(world, snaps, str(VIDEO), fps=20, progress=_prog)

        try:
            await asyncio.to_thread(_job)
            url = f"/static/fleet_demo.mp4?t={int(time.time())}"
            self.export_state = {"status": "done", "pct": 100, "url": url}
            await self.broadcast({"type": "export", "status": "done", "url": url})
        except Exception as e:  # noqa: BLE001
            self.export_state = {"status": "error", "pct": 0, "url": None}
            await self.broadcast({"type": "export", "status": "error", "msg": str(e)})


session = Session()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(session.loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="FleetNet Dashboard", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    session.clients.add(ws)
    await ws.send_json(session.layout_msg())
    await ws.send_json(session.frame_msg())
    if session.export_state["status"] == "done":
        await ws.send_json({"type": "export", "status": "done",
                            "url": session.export_state["url"]})
    try:
        while True:
            await ws.receive_text()          # inbound ignored; controls are POST
    except WebSocketDisconnect:
        session.clients.discard(ws)
    except Exception:
        session.clients.discard(ws)


@app.post("/api/config")
async def api_config(payload: dict):
    await session.reconfigure(
        _clamp(payload.get("n_robots"), 1, C.MAX_ROBOTS, 4),
        _clamp(payload.get("n_tasks"), 1, C.MAX_TASKS, 10),
        _clamp(payload.get("seed"), 0, 10_000, 7),
    )
    return {"ok": True, "config": session.sim.cfg()}


@app.post("/api/control")
async def api_control(payload: dict):
    action = payload.get("action")
    if action == "start":
        session.running = True
    elif action == "pause":
        session.running = False
    elif action == "reset":
        await session.reset()
    elif action == "step":
        async with session.lock:
            session.sims["stack"].step()
            if session.benchmark:
                session.sims["stopwait"].step()
        await session.broadcast(session.frame_msg())
    elif action == "speed":
        session.speed = max(0.25, min(4.0, float(payload.get("value", 1))))
    await session.broadcast({"type": "status", "running": session.running,
                             "speed": session.speed})
    return {"ok": True, "running": session.running, "speed": session.speed}


@app.post("/api/event")
async def api_event(payload: dict):
    async with session.lock:
        for s in session.sims.values():
            s.inject_event(payload.get("kind"), payload.get("payload"))
    await session.broadcast(session.frame_msg())
    return {"ok": True}


@app.post("/api/benchmark")
async def api_benchmark(payload: dict):
    session.benchmark = bool(payload.get("on"))
    # rebuild both sims at tick 0 so the two arenas start in perfect lockstep
    await session.reset()
    return {"ok": True, "benchmark": session.benchmark}


@app.post("/api/export")
async def api_export():
    asyncio.create_task(session.export())
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
