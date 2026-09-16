# FleetNet — Live Decentralised-Fleet Dashboard

A professional operations console for the decentralised multi-AMR warehouse
simulation.  You choose the number of robots and tasks, start a run, and watch
the five algorithm layers coordinate the fleet in real time — then inject
disturbances live and export the run to MP4.

**The Python engine (`engine/`) computes every robot's motion.**  The browser is
a pure view + control surface.  Nothing about the movement is scripted — the
"Algorithm Activity" panel shows the layers computing every tick.

```
Layer 1  D* Lite       per-robot route around racks & dropped boxes
Layer 2  MAPF/MD-PIBT  conflict-free next-cell + priority inheritance
Layer 3  NH-ORCA       reciprocal close-range collision avoidance (LP)
Layer 4  ACBBA         auction task allocation + re-auction on fault / low battery
Layer 5  Comms mesh    Wi-Fi dead zone -> CONNECTIVITY_LOST "act alone" fallback
```

---

## Run it

```bash
cd dashboard
./run.sh                     # first run builds .venv, then serves
# → open http://127.0.0.1:8000
```

Manual equivalent:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

If you already set up `../demo_simulation/.venv`, it has every dependency and can
run this directly:

```bash
../demo_simulation/.venv/bin/python server.py
```

`ffmpeg` is needed only for **Export MP4** (already present on most Arch installs;
otherwise `sudo pacman -S ffmpeg`).  Without it, export falls back to a GIF.

Quick engine check with no server / UI:

```bash
.venv/bin/python headless.py --robots 6 --tasks 15 --seed 7
```

---

## Using the dashboard

| Area | What it does |
|---|---|
| **Configure** | Robots 1–6, Tasks 1–20, seed → **Apply & Reset** rebuilds the sim |
| **Run** | Start / Pause / Step / Reset, playback speed 0.5×–4× |
| **Inject** | *Drop Box* then click a cell or drag a rectangle · *Clear Boxes* · *Dead Zone* then drag a rectangle · *Clear Zones* · *Fail* / *Recover* a robot · *Kill Dashboard* |
| **Benchmark** | *A/B vs stop-and-wait* — run the same scenario twice side-by-side, the 5-layer stack against a naive stop-and-wait baseline, with a live Comparison Scoreboard (toggling it restarts the run) |
| **Fleet Map** | live robot positions, planned D\* Lite paths, pickup / drop-off stations, chargers, the **standby depot** (numbered parking bays, bottom-centre), dead zones, dropped boxes, optional congestion heat |
| **Robot Status** | per-robot mode, task, battery, location, speed, heartbeat, link |
| **Task Board** | queued → active → done, assignee, ETA, RE-ROUTED flag |
| **Algorithm Activity** | D\* Lite replans, MD-PIBT pushes, robots avoiding, mesh status, last ACBBA auction |
| **Replay & Video** | scrub the buffered run instantly; **Export MP4** renders it and plays it inline |
| **Fleet Summary / Event Log** | utilisation, battery, mode counts, timestamped events |

### Demo script (what to show an observer)
1. Configure **6 robots / 15 tasks**, Apply, Start.
2. **Drop Box** — click one cell or drag a rectangle to wall off a whole area —
   on an aisle a robot is using → its path re-computes; task gets a
   RE-ROUTED tag; "D\* Lite replans" ticks up.
3. **Dead Zone** dragged over a moving robot → its card flips to COMMS-LOST, it
   slows to caution speed, ring turns purple.
4. **Fail** a robot → ACBBA re-auctions its task (see Event Log / Task Board).
5. **Kill Dashboard** → banner shows, robots keep working (fully decentralised).
6. Let the queue drain → each robot that runs out of work drives to the
   **standby depot** and parks in a numbered bay (card shows `PARKED`); it pulls
   straight back out the moment ACBBA hands it a new task. KPIs populate;
   **Export MP4** and play it back inline.
7. Tick **A/B vs stop-and-wait**, Start → watch the baseline gridlock (stuck
   robots, rising "Deadlock robot-seconds") while the stack keeps flowing; the
   Comparison Scoreboard calls the winner.

### Benchmark mode — how the comparison is fair

Both arenas run the **same** seed, task list, battery levels, D\* Lite planning,
ACBBA allocation, mesh comms and failure-recovery. The **only** difference is
Layer 2 + Layer 3.

- **Stack:** MD-PIBT priority inheritance + NH-ORCA — *proactive* coordination
  (robots resolve a conflict before it becomes a stall).
- **Baseline:** stop-and-wait with the standard industrial recovery layer —
  single-cell reservation (halt when the next cell is taken), **plus**
  timeout-triggered priority override (a long-waiting robot jumps the queue for a
  contested cell) and a **reactive D\* Lite detour** around a robot that is
  permanently blocking it. It is *not* a strawman; it recovers from deadlock —
  just reactively, and at a cost.

Scored metrics: tasks completed, throughput (tasks/min, frozen at makespan),
makespan, currently-stuck robots, cumulative deadlock robot-seconds. Context
(not scored): detour recovery cost — the extra distance the baseline's reroutes
added (the stack never reroutes reactively, so it is 0 by construction).

What the numbers show: the stack **never gridlocks** — 0 deadlock robot-seconds,
always completes every task. The recovering baseline completes too in open
conditions and can even be a little quicker at low robot counts (its coordination
overhead is nil), but it still logs hundreds–thousands of deadlock robot-seconds,
strands tasks under disturbance, and pays the detour tax. The stack's margin
widens with fleet size, congestion and injected disturbances (boxes, dead zones,
faults). A run that never converges is capped at `BENCH_TICK_CAP` ticks.

Headless check:
`.venv/bin/python headless.py --benchmark --robots 6 --tasks 18 --seed 7 --ticks 5000`

---

## Files

```
dashboard/
  engine/
    config.py        parameters, layout, battery model, scripted timeline
    world.py         occupancy grid + pickup / drop-off / charger stations
    algcore/         vendored reference algorithms (copied from ../algorithms/)
    planner.py       Layer 1  — D* Lite incremental planner + distance field
    coordinator.py   Layer 2  — MD-PIBT (dynamic priorities + backtracking)
    avoidance.py     Layer 3  — NH-ORCA linear-program collision avoidance
    allocator.py     Layer 4  — ACBBA bundle build + consensus allocation
    comms.py         Layer 5  — Zenoh-style pub/sub mesh + dead zones
    strategies.py    Layer 2+3 seam — StackStrategy vs StopWaitStrategy (benchmark)
    robot.py         robot state, battery, kinematics
    simulation.py    the tick loop + rich per-tick snapshot + inject_event()
    render.py        snapshot list -> MP4 (matplotlib, CPU only)
  server.py          FastAPI: step loop(s), WebSocket stream, control + benchmark endpoints
  static/            index.html · style.css · app.js  (no build step, no CDN)
  headless.py        engine-only sanity check ( + --benchmark A/B run )
```

## Failure handling

- **Rate-limited planning** — after D\* Lite reports "no path" a robot backs off
  `REPLAN_BACKOFF` ticks (or replans immediately if the map changes). Boxing a
  goal in no longer causes thousands of A\* calls per second.
- **Safe-hold (degraded mode)** — a robot with no reachable route stops where it
  is (mode `stranded`), its task is released for re-auction, and an alert is
  logged. A charge trip is kept and retried on the back-off timer.
- **Blocked tasks** — after 3 fleet-wide unreachable attempts a task is marked
  `blocked` (needs manual intervention) and stops being auctioned.
- **Recovery** — **Clear Boxes** removes dropped obstacles; stranded robots
  re-plan and resume, blocked tasks are re-queued.

## Honesty notes (for Q&A)
- Each layer now runs the **real reference algorithm** from `engine/algcore/`
  (vendored verbatim from the repo-root `algorithms/` folder): D* Lite,
  MD-PIBT, NH-ORCA (2-D ORCA LP + NH radius inflation), ACBBA (bundle +
  consensus table). The ACBBA bundle length is 1 because each robot services
  one job at a time; a fresh consensus round runs per auction event.
- MD-PIBT's congestion term is an added **heuristic heat-map cost** on top of
  the paper's distance-to-goal ranking (stand-in for a learned policy).
- The comms layer runs the real **router-mediated pub/sub** routing, but the
  transport is still *modelled* — real deployment is ROS 2 over Zenoh over a
  Wi-Fi mesh. The sim proves the routing + fallback behaviour, not the wire.
- No absolute performance numbers are claimed — this is an architecture /
  behaviour demo. The benchmark's numbers are **relative** (stack vs. baseline on
  an identical scenario), which is the honest way to show the coordination layer
  earns its keep.
