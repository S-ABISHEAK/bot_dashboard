"""Central-corridor archetype (Section B): one dominant spine aisle the
length of the building, storage blocks branch off both sides via
perpendicular feeder aisles.

This reuses ``grid``'s field builder wholesale — the grid's mandatory
front/back spine aisles (added in ``generation.storage`` specifically to
guarantee connectivity) already play the "dominant spine" role structurally;
this module's only real job is relabeling that spine's archetype_role to
``spine`` (vs. plain ``main``) and its secondary aisles conceptually read
as "feeders" for anyone consuming the ``archetype_role`` metadata
downstream (e.g. a future traffic model that treats spine/feeder
differently from a same-width ordinary main aisle).
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.enums import ArchetypeRole
from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.archetypes import grid
from fleetnet_layout.generation.types import LayoutBuildResult


def build(rng: np.random.Generator, cfg: LayoutConfig) -> LayoutBuildResult:
    result = grid.build(rng, cfg)
    for aisle in result.cross_aisles:
        if aisle.metadata.get("spine"):
            aisle.metadata["archetype_role"] = ArchetypeRole.SPINE.value
    for aisle in result.secondary_aisles:
        aisle.metadata["archetype_role"] = ArchetypeRole.FEEDER.value
    return result
