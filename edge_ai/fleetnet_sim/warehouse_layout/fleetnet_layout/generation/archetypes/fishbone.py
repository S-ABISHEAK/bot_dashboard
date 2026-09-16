"""Fishbone / angled-picking archetype (Section B).

KNOWN LIMITATION (v1): true fishbone geometry (angled, non-90-degree
picking aisles feeding a central diagonal cross-aisle) needs a
genuinely different geometric construction than the orthogonal grid
this package's field builder produces, and the research spec itself
flags fishbone as the lowest-priority, most implementation-costly
archetype ("Medium — nontrivial geometry," weighted lowest in Section
K's categorical distribution, explicitly called out in Section AF as
"implement last"). This version reuses ``grid``'s orthogonal field
wholesale so every archetype in the registry still produces a valid,
connected layout — angled geometry is deferred to a future revision
rather than shipped half-working.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.archetypes import grid
from fleetnet_layout.generation.types import LayoutBuildResult


def build(rng: np.random.Generator, cfg: LayoutConfig) -> LayoutBuildResult:
    return grid.build(rng, cfg)
