"""Matplotlib renderer: turns a list of per-tick snapshots into an MP4
(or GIF fallback).  Pure CPU, Agg backend - no GPU.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
import numpy as np

from . import config as C

LAYERS = [
    ("1 D* Lite",  "route around racks / dropped boxes"),
    ("2 MD-PIBT",  "MAPF — conflict-free next cell + priority inherit"),
    ("3 NH-ORCA",  "reciprocal close-range collision dodging (LP)"),
    ("4 ACBBA",    "bundle + consensus allocation, re-win on fault"),
    ("5 Mesh",     "Zenoh-style pub/sub + CONNECTIVITY_LOST fallback"),
]
BG = "#0e1320"
INK = "#e6ecf5"


def _base_image(world):
    img = np.zeros((world.h, world.w, 3), dtype=float)
    img[:] = (0.055, 0.075, 0.11)
    img[world.grid] = (0.16, 0.19, 0.25)
    return img


def animate(world, snapshots, out_path, fps=20, dpi=120, progress=None):
    fig = plt.figure(figsize=(15, 7.3), facecolor=BG)
    ax = fig.add_axes([0.03, 0.06, 0.63, 0.88])
    panel = fig.add_axes([0.68, 0.06, 0.30, 0.88])
    panel.axis("off")
    ax.set_facecolor(BG)
    ax.set_xlim(0, world.w)
    ax.set_ylim(0, world.h)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#243044")

    ax.imshow(_base_image(world), extent=[0, world.w, 0, world.h],
              origin="lower", interpolation="nearest", zorder=0)
    heat = ax.imshow(np.zeros((world.h, world.w)), extent=[0, world.w, 0, world.h],
                     origin="lower", cmap="inferno", alpha=0.20, vmin=0, vmax=8,
                     interpolation="bilinear", zorder=1)

    for (x, y) in world.pickups:
        ax.add_patch(Rectangle((x - 0.42, y - 0.42), 0.84, 0.84, fill=False,
                               ec="#22c55e", lw=1.6, zorder=2))
    for (x, y) in world.dropoffs:
        ax.add_patch(Rectangle((x - 0.42, y - 0.42), 0.84, 0.84, fill=False,
                               ec="#4f8cff", lw=1.6, zorder=2))
    for (x, y) in world.chargers:
        ax.add_patch(Rectangle((x - 0.42, y - 0.42), 0.84, 0.84, color="#f59e0b",
                               alpha=0.85, zorder=2))
        ax.text(x, y, "⚡", ha="center", va="center", fontsize=9, zorder=3)

    depot = getattr(world, "depot", None)
    if depot:
        dxs = [p[0] for p in depot]
        dys = [p[1] for p in depot]
        x0, y0 = min(dxs) - 0.5, min(dys) - 0.5
        bw = max(dxs) - min(dxs) + 1
        bh = max(dys) - min(dys) + 1
        ax.add_patch(Rectangle((x0 - 0.18, y0 - 0.18), bw + 0.36, bh + 0.36,
                               fill=True, fc="#94a3b8", alpha=0.10,
                               ec="#94a3b8", ls="--", lw=1.1, zorder=1))
        for i, (sx, sy) in enumerate(depot):
            ax.add_patch(Rectangle((sx - 0.38, sy - 0.38), 0.76, 0.76, fill=False,
                                   ec="#94a3b8", lw=1.1, zorder=2))
            ax.text(sx, sy, str(i + 1), ha="center", va="center", fontsize=6,
                    color="#8b95a5", zorder=3)
        ax.text(x0 - 0.15, y0 - 0.42, "STANDBY DEPOT", fontsize=7,
                color="#aeb8c6", ha="left", va="bottom", zorder=3)

    dz_patches = [Rectangle((0, 0), 0, 0, fc="#f59e0b", alpha=0.14,
                            ec="#f59e0b", ls="--", lw=1.2, zorder=1) for _ in range(8)]
    for p in dz_patches:
        ax.add_patch(p)

    obst = ax.scatter([], [], marker="s", s=90, c="#ef4444", zorder=4)

    rp, rl, pl = [], [], []
    for rb in snapshots[0]["robots"]:
        c = Circle((0, 0), C.ROBOT_RADIUS, facecolor=rb["color"],
                   edgecolor="w", lw=1.4, zorder=6)
        ax.add_patch(c); rp.append(c)
        rl.append(ax.text(0, 0, rb["name"].split("-")[-1], ha="center", va="center",
                          fontsize=7, color="w", zorder=7, weight="bold"))
        ln, = ax.plot([], [], "-", color=rb["color"], lw=1.4, alpha=0.55, zorder=5)
        pl.append(ln)

    title = ax.set_title("", fontsize=12, loc="left", color=INK, pad=10)
    note = ax.text(0.5, -0.045, "", transform=ax.transAxes, ha="center",
                   fontsize=10, color="#f59e0b", weight="bold")
    banner = ax.text(0.5, 0.6, "CENTRAL DASHBOARD KILLED\nfleet keeps running — no coordinator",
                     transform=ax.transAxes, ha="center", va="center", visible=False,
                     fontsize=14, color="#ef4444", weight="bold", zorder=10,
                     bbox=dict(boxstyle="round", fc="#0e1320", ec="#ef4444"))
    corner = ax.text(0.015, 0.978, "", transform=ax.transAxes, ha="left", va="top",
                     fontsize=9, color="#ef4444", weight="bold", zorder=10)
    ptxt = panel.text(0.0, 1.0, "", va="top", ha="left", fontsize=8.7,
                      family="monospace", color=INK)

    def frame(k):
        s = snapshots[k]
        hm = np.zeros((world.h, world.w))
        title.set_text(f"Decentralised Warehouse Fleet   t={s['tick'] * C.DT:5.1f}s"
                       f"    tasks {s['done']}/{s['total']}")
        note.set_text(s["note"])
        if s["obstacles"]:
            obst.set_offsets([[x + 0.5, y + 0.5] for (x, y) in s["obstacles"]])
        else:
            obst.set_offsets(np.empty((0, 2)))

        for i, p in enumerate(dz_patches):
            if i < len(s["dead_zones"]):
                x, y, w, h = s["dead_zones"][i]
                p.set_bounds(x, y, w, h)
            else:
                p.set_bounds(0, 0, 0, 0)

        for i, rb in enumerate(s["robots"]):
            rp[i].center = (rb["pos"][0], rb["pos"][1])
            rl[i].set_position((rb["pos"][0], rb["pos"][1]))
            edge = ("#ef4444" if not rb["alive"] else
                    "#a855f7" if not rb["connected"] else
                    "#f59e0b" if rb["avoiding"] else
                    "#8b95a5" if rb["mode"] == "parked" else "w")
            rp[i].set_edgecolor(edge)
            rp[i].set_linewidth(3.0 if edge not in ("w", "#8b95a5") else 1.4)
            if rb["path"] and len(rb["path"]) > 1:
                rp_xs = [p[0] + 0.5 for p in rb["path"]]
                rp_ys = [p[1] + 0.5 for p in rb["path"]]
                pl[i].set_data(rp_xs, rp_ys)
            else:
                pl[i].set_data([], [])
            cx, cy = rb["cell"]
            hm[cy, cx] += 4

        sk = s["since_kill"]
        banner.set_visible(sk is not None and sk < 55)
        corner.set_text("" if s["dashboard"] else "●  DASHBOARD OFFLINE  (fully decentralised)")

        lines = ["ALGORITHM STACK — all layers live\n"]
        for tag, desc in LAYERS:
            lines.append(f"  {tag:<11}{desc}")
        lines.append("\nROBOT STATE")
        for rb in s["robots"]:
            st = ("FAULT" if not rb["alive"] else
                  "COMMS-LOST" if not rb["connected"] else rb["mode"])
            lines.append(f"  {rb['name']:<7} P{rb['priority']}  {rb['battery']:>4.0f}%  {st}")
        lines.append("\nEVENT LOG")
        for e in s["events"][-7:]:
            lines.append(f"  {e['msg'][:44]}")
        ptxt.set_text("\n".join(lines))
        heat.set_data(hm)
        return []

    n = len(snapshots)
    anim = FuncAnimation(fig, frame, frames=n, interval=1000 / fps, blit=False)

    def _cb(i, tot):
        if progress:
            progress(i + 1, tot)
        elif i % 25 == 0 or i == tot - 1:
            print(f"  rendering frame {i + 1}/{tot}", end="\r")

    try:
        anim.save(out_path, writer=FFMpegWriter(fps=fps, bitrate=2600),
                  dpi=dpi, savefig_kwargs={"facecolor": BG}, progress_callback=_cb)
        print(f"\nSaved {out_path}")
        result = out_path
    except Exception as e:
        gif = out_path.rsplit(".", 1)[0] + ".gif"
        print(f"\nffmpeg failed ({e}); GIF -> {gif}")
        anim.save(gif, writer=PillowWriter(fps=fps), dpi=90,
                  savefig_kwargs={"facecolor": BG}, progress_callback=_cb)
        result = gif
    plt.close(fig)
    return result
