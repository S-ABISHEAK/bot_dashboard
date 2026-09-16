"""Renders a ``ReplayData`` (see loader.py) as an animated GIF: the
static warehouse background drawn once via ``fleetnet_layout``'s
``draw_layout_static``, robots overlaid per sampled tick (colored by
task state, with a short fading trail), active conflicts
(``ConflictResolver.dependency_edges``, the real pairwise ground truth —
same source ``datasets/conflict_builder.py`` uses) drawn as a line
between the two robots involved, and congestion-detour events marked
with a star. Everything drawn comes straight from stored telemetry —
nothing here reruns or re-derives the simulation.
"""
from __future__ import annotations

from collections import defaultdict, deque

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.lines import Line2D

from fleetnet_layout.visualization.renderer import draw_layout_static

from fleetnet_sim.replay.loader import ReplayData

_TASK_STATE_COLORS = {
    "IDLE": "#adb5bd",
    "TO_PICKUP": "#e63946",
    "PICKING": "#f4a261",
    "TO_DROPOFF": "#2a9d8f",
    "DROPPING": "#264653",
}
_DEFAULT_COLOR = "#000000"


def render_replay(
    data: ReplayData,
    output_path: str,
    fps: int = 10,
    trail_length: int = 15,
    start_time: float | None = None,
    end_time: float | None = None,
    show_graph: bool = False,
    title: str | None = None,
) -> int:
    """Renders to ``output_path`` (``.gif``, via Pillow — no external
    ffmpeg dependency). Returns the number of frames actually rendered."""
    ticks = data.ticks
    if start_time is not None:
        ticks = [t for t in ticks if data.tick_to_time[t] >= start_time]
    if end_time is not None:
        ticks = [t for t in ticks if data.tick_to_time[t] <= end_time]
    if not ticks:
        raise ValueError("no sampled ticks fall within [start_time, end_time] for this run")

    fig, ax = plt.subplots(figsize=(10, 10 * data.layout.result.footprint.h / max(data.layout.result.footprint.w, 1e-6) or 10))
    draw_layout_static(ax, data.layout, show_graph=show_graph, show_ids=False, show_exclusions=True, show_bottlenecks=False)
    ax.set_title(title or f"run {data.run_id}")

    scat = ax.scatter([], [], s=45, zorder=20, edgecolors="black", linewidths=0.4)
    time_text = ax.text(
        0.01, 0.99, "", transform=ax.transAxes, va="top", ha="left", fontsize=9, zorder=40,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="none"),
    )
    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markeredgecolor="black", markersize=8, label=state)
        for state, c in _TASK_STATE_COLORS.items()
    ] + [
        Line2D([0], [0], color="gold", lw=2, label="active conflict"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor="magenta", markersize=12, label="congestion detour"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=7, framealpha=0.85)

    trail_lines: dict[str, Line2D] = {}
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=trail_length))
    dynamic_artists: list = []

    def update(frame_idx: int):
        nonlocal dynamic_artists
        for artist in dynamic_artists:
            artist.remove()
        dynamic_artists = []

        tick = ticks[frame_idx]
        robots = data.robots_by_tick.get(tick, [])
        xs = [r["x"] for r in robots]
        ys = [r["y"] for r in robots]
        colors = [_TASK_STATE_COLORS.get(r["task_state"], _DEFAULT_COLOR) for r in robots]
        scat.set_offsets(list(zip(xs, ys)) or [[float("nan"), float("nan")]])
        scat.set_facecolor(colors)

        pos_by_id = {}
        for r in robots:
            pos_by_id[r["robot_id"]] = (r["x"], r["y"])
            history[r["robot_id"]].append((r["x"], r["y"]))
            pts = list(history[r["robot_id"]])
            line = trail_lines.get(r["robot_id"])
            if line is None:
                (line,) = ax.plot([], [], lw=1.0, alpha=0.35, zorder=15, color=_TASK_STATE_COLORS.get(r["task_state"], _DEFAULT_COLOR))
                trail_lines[r["robot_id"]] = line
            xs_t, ys_t = zip(*pts)
            line.set_data(xs_t, ys_t)
            line.set_color(_TASK_STATE_COLORS.get(r["task_state"], _DEFAULT_COLOR))

        for a, b in data.conflict_edges_by_tick.get(tick, []):
            if a in pos_by_id and b in pos_by_id:
                (x1, y1), (x2, y2) = pos_by_id[a], pos_by_id[b]
                (ln,) = ax.plot([x1, x2], [y1, y2], color="gold", lw=2.0, alpha=0.85, zorder=25)
                dynamic_artists.append(ln)

        for rid in data.detour_robots_by_tick.get(tick, []):
            if rid in pos_by_id:
                x, y = pos_by_id[rid]
                mk = ax.scatter([x], [y], marker="*", s=220, color="magenta", zorder=26, edgecolors="black", linewidths=0.5)
                dynamic_artists.append(mk)

        time_text.set_text(f"t={data.tick_to_time[tick]:.1f}s  tick={tick}  robots={len(robots)}")
        return [scat, time_text, *trail_lines.values(), *dynamic_artists]

    anim = FuncAnimation(fig, update, frames=len(ticks), interval=1000.0 / fps, blit=False)
    anim.save(output_path, writer=PillowWriter(fps=fps))
    plt.close(fig)
    return len(ticks)
