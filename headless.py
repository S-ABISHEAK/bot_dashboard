"""Quick engine sanity check (no server, no video).

    python headless.py --robots 6 --tasks 15 --seed 7
"""
import argparse

from engine import config as C
from engine.simulation import Simulation


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=4)
    ap.add_argument("--tasks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ticks", type=int, default=C.TOTAL_TICKS)
    ap.add_argument("--scripted", action="store_true")
    ap.add_argument("--benchmark", action="store_true",
                    help="run the 5-layer stack vs. the stop-and-wait baseline")
    args = ap.parse_args()

    if args.benchmark:
        return _benchmark(args)

    sim = Simulation(n_robots=args.robots, n_tasks=args.tasks,
                     seed=args.seed, scripted=args.scripted)
    snaps = sim.run(args.ticks)
    last = snaps[-1]
    print(f"robots={sim.n} tasks={sim.n_tasks} ticks={sim.tick}")
    print(f"completed {last['kpi']['completed']}/{last['kpi']['total']}  "
          f"avg_completion={last['kpi']['avg_completion_s']}s  "
          f"conflicts={last['kpi']['conflicts']}  near_miss={last['kpi']['near_miss']}  "
          f"avoided={last['kpi']['avoided']}  fleet_util={last['kpi']['fleet_util']}")
    for e in sim.event_log[-12:]:
        print(f"  t{e['t']:>6}  {e['msg']}")


def _benchmark(args):
    a = Simulation(n_robots=args.robots, n_tasks=args.tasks, seed=args.seed)
    b = Simulation(n_robots=args.robots, n_tasks=args.tasks, seed=args.seed,
                   coordination="stopwait")
    done = lambda s: s.alloc.done_count() == len(s.alloc.tasks)
    for _ in range(args.ticks):
        if not done(a):
            a.step()
        if not done(b):
            b.step()
        if done(a) and done(b):
            break
    print(f"robots={a.n} tasks={a.n_tasks} ticks={args.ticks} seed={args.seed}")
    for tag, s in (("STACK", a), ("STOP-WAIT", b)):
        k = s.snapshots[-1]["kpi"]
        print(f"  [{tag:9}] completed={k['completed']}/{k['total']}  "
              f"makespan={k['makespan_s']}s  avg={k['avg_completion_s']}s  "
              f"throughput={k['throughput_per_min']}/min  "
              f"stuck_now={k['stuck_robots']}  "
              f"deadlock_robot_s={k['deadlock_robot_s']}  "
              f"detours={k['detour_count']} (+{k['detour_extra_m']}m / {k['detour_extra_pct']}%)  "
              f"near_miss={k['near_miss']}  util={k['fleet_util']}")


if __name__ == "__main__":
    main()
