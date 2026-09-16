"""Axis-segmentation helper shared by every archetype's field builder.

The core geometric primitive across all archetypes is: divide a length
into N items separated by N-1 gaps, where items are rack rows/blocks/
travel-segments and gaps are aisles. ``fit_segments`` is the one place
that reconciles a *sampled target count* against the *physically
available length* — if the target doesn't fit, it shrinks the count
(and, as a last resort, the item/gap sizes) rather than ever producing
overlapping or out-of-bounds geometry. This is what keeps every
archetype builder simple: they call this once per axis and trust the
result fits exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fleetnet_layout.config.enums import AisleWidthClass
from fleetnet_layout.geometry.primitives import GeoObject


@dataclass(frozen=True)
class AxisSegments:
    count: int
    item_size: float
    gap_size: float
    item_starts: tuple[float, ...]

    def gaps(self) -> list[tuple[float, float]]:
        """Return (start, size) for each of the count-1 inter-item gaps."""
        out = []
        for i in range(self.count - 1):
            start = self.item_starts[i] + self.item_size
            out.append((start, self.gap_size))
        return out


def fit_segments(total_length: float, target_count: int, item_size: float, gap_size: float, min_count: int = 1) -> AxisSegments:
    count = max(min_count, target_count)

    def needed(n: int) -> float:
        return n * item_size + max(n - 1, 0) * gap_size

    while count > min_count and needed(count) > total_length + 1e-9:
        count -= 1

    total_needed = needed(count)
    actual_item, actual_gap = item_size, gap_size
    if total_needed > total_length + 1e-9:
        if count <= 1:
            actual_item = max(min(item_size, total_length), 1e-3)
            actual_gap = 0.0
        else:
            scale = total_length / total_needed
            actual_item = item_size * scale
            actual_gap = gap_size * scale
    elif total_needed < total_length - 1e-9:
        # Stretch items (never gaps — aisle width is equipment-driven, not
        # filler, per Section C) to use the full available length exactly.
        # Leaving a leftover remainder here is a real bug, not a harmless
        # rounding gap: nothing occupies that space (no rack, no aisle),
        # which silently orphans anything beyond it — e.g. a depth-axis
        # segmentation with room for only one interval-sized travel
        # segment used to leave the back half of the field's depth
        # completely disconnected from the far spine (caught by
        # tests/test_graph.py's zone_based connectivity check).
        extra = total_length - total_needed
        actual_item = item_size + extra / count

    starts = []
    cursor = 0.0
    for _ in range(count):
        starts.append(cursor)
        cursor += actual_item + actual_gap

    return AxisSegments(count=count, item_size=actual_item, gap_size=actual_gap, item_starts=tuple(starts))


_ONE_WAY_ELIGIBLE = {AisleWidthClass.NARROW_VNA.value, AisleWidthClass.NARROW.value}


def assign_one_way(rng: np.random.Generator, aisles: list[GeoObject], ratio: float) -> None:
    """Mutates aisle metadata in place: narrow/VNA aisles are the only
    ones eligible to be one-way (Section C: "narrow/VNA aisles are
    almost always one-way; main aisles are typically two-way"). Exactly
    `ratio` fraction of the eligible set is flipped one-way."""
    eligible = [a for a in aisles if a.metadata.get("width_class") in _ONE_WAY_ELIGIBLE]
    if not eligible or ratio <= 0:
        return
    n = max(0, round(len(eligible) * ratio))
    if n == 0:
        return
    chosen = rng.choice(len(eligible), size=min(n, len(eligible)), replace=False)
    directions = ["forward", "backward"]
    for idx in chosen:
        eligible[idx].metadata["one_way"] = True
        eligible[idx].metadata["direction"] = directions[int(rng.integers(0, 2))]
