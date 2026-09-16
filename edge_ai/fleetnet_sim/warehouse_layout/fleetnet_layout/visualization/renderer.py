"""Matplotlib 2D renderer (Section AD) — debugging/validation aid, not a
simulator. Renders footprint, racks, aisles (color-coded by
archetype_role), zones, docks, columns, exclusions, and optionally the
navigation graph and top bottleneck candidates.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon

from fleetnet_layout.generation.generator import GeneratedLayout

_AISLE_COLORS = {
    "main": "#f4a261",
    "spine": "#e76f51",
    "secondary": "#e9c46a",
    "feeder": "#e9c46a",
    "cross": "#f6d55c",
    "zone_access": "#cccccc",
}
_ZONE_COLORS = {
    "receiving": "#2a9d8f",
    "shipping": "#264653",
    "staging": "#8ab17d",
    "picking": "#e07a5f",
    "packing": "#f2cc8f",
    "returns": "#81b29a",
    "charging": "#3d405b",
    "office": "#bdb2ff",
}


def _draw_polygon(ax, points, facecolor, edgecolor="black", alpha=1.0, zorder=1, lw=0.3):
    patch = MplPolygon(points, closed=True, facecolor=facecolor, edgecolor=edgecolor, alpha=alpha, zorder=zorder, linewidth=lw)
    ax.add_patch(patch)


def draw_layout_static(
    ax,
    layout: GeneratedLayout,
    show_graph: bool = True,
    show_ids: bool = False,
    show_exclusions: bool = True,
    show_bottlenecks: bool = True,
) -> None:
    """Draws footprint/racks/aisles/zones/docks(/graph/bottlenecks) onto
    an existing ``Axes`` — factored out of ``render_layout`` so other
    tools (e.g. fleetnet_sim's replay viewer) can draw the same static
    background and then overlay their own per-frame content on top,
    without duplicating this drawing logic."""
    result = layout.result

    _draw_polygon(ax, result.footprint.to_points(), facecolor="white", edgecolor="black", lw=1.5, zorder=0)

    for rack in result.racks:
        _draw_polygon(ax, rack.points, facecolor="#457b9d", edgecolor="#1d3557", alpha=0.85, zorder=2)

    for aisle in result.all_aisles:
        role = aisle.metadata.get("archetype_role", "secondary")
        color = _AISLE_COLORS.get(role, "#eeeeee")
        _draw_polygon(ax, aisle.points, facecolor=color, edgecolor="none", alpha=0.5, zorder=1)

    for zone in result.zones:
        zt = zone.metadata.get("zone_type", "")
        color = _ZONE_COLORS.get(zt, "#dddddd")
        _draw_polygon(ax, zone.points, facecolor=color, edgecolor="black", alpha=0.6, zorder=1, lw=0.5)
        cx, cy = zone.centroid
        ax.text(cx, cy, zt, ha="center", va="center", fontsize=6, zorder=5)

    for dock in result.docks:
        _draw_polygon(ax, dock.points, facecolor="black", edgecolor="none", zorder=4)

    if show_exclusions:
        for col in result.columns:
            _draw_polygon(ax, col.points, facecolor="red", edgecolor="none", zorder=6)
        for excl in result.exclusions:
            _draw_polygon(ax, excl.points, facecolor="purple", alpha=0.5, edgecolor="black", zorder=3)

    if show_graph:
        g = layout.graph
        for u, v, attrs in g.edges(data=True):
            x1, y1 = g.nodes[u]["x"], g.nodes[u]["y"]
            x2, y2 = g.nodes[v]["x"], g.nodes[v]["y"]
            ax.plot([x1, x2], [y1, y2], color="black", linewidth=0.4, alpha=0.4, zorder=7)
        for n, attrs in g.nodes(data=True):
            c = "red" if attrs.get("dead_end") else ("blue" if attrs.get("node_type") == "intersection" else "gray")
            ax.plot(attrs["x"], attrs["y"], marker="o", markersize=1.5, color=c, zorder=8)
            if show_ids:
                ax.text(attrs["x"], attrs["y"], n, fontsize=3, zorder=9)

    if show_bottlenecks:
        g = layout.graph
        for cand in layout.metrics.bottleneck_candidates[:5]:
            u, v = cand["edge"]
            if u in g.nodes and v in g.nodes:
                x1, y1 = g.nodes[u]["x"], g.nodes[u]["y"]
                x2, y2 = g.nodes[v]["x"], g.nodes[v]["y"]
                ax.plot([x1, x2], [y1, y2], color="magenta", linewidth=2.0, alpha=0.8, zorder=10)

    ax.set_xlim(-2, result.footprint.w + 2)
    ax.set_ylim(-2, result.footprint.h + 2)
    ax.set_aspect("equal")


def render_layout(
    layout: GeneratedLayout,
    save_path: str,
    show_graph: bool = True,
    show_ids: bool = False,
    show_exclusions: bool = True,
    show_bottlenecks: bool = True,
    title: str | None = None,
) -> None:
    result = layout.result
    fig, ax = plt.subplots(figsize=(12, 12 * result.footprint.h / max(result.footprint.w, 1e-6) or 12))
    draw_layout_static(ax, layout, show_graph=show_graph, show_ids=show_ids, show_exclusions=show_exclusions, show_bottlenecks=show_bottlenecks)
    ax.set_title(title or f"{layout.config.warehouse.archetype.value} / {layout.config.warehouse.industry_type.value} / seed={layout.config.warehouse.seed}")
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
