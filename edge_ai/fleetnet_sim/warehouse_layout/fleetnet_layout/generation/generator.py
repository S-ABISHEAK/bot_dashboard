"""Top-level orchestrator (Section AK): seed -> sampled config -> archetype
build -> graph -> validate -> metrics -> JSON-ready result, with
resample-on-reject.

On validation failure, only the config subsection(s) the failures are
tagged to (``ValidationResult.resample_tags``) get re-sampled — a fresh
seed derived from the original via a counter, not a full restart — up
to ``max_attempts``. Exhausting attempts raises ``LayoutGenerationError``
with reason/stage/parameters/seed (Section AK), never silently emitting
an invalid layout.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from fleetnet_layout.config.enums import Archetype
from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.archetypes import (
    central_corridor,
    fishbone,
    flow_through,
    grid,
    l_flow,
    u_flow,
    zone_based,
)
from fleetnet_layout.generation.sampling import SamplingOverrides, sample_config
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.graph.builder import build_navigation_graph
from fleetnet_layout.graph.metrics import compute_metrics
from fleetnet_layout.validation.validator import ValidationResult, validate_layout

_ARCHETYPE_BUILDERS = {
    Archetype.GRID: grid.build,
    Archetype.FLOW_THROUGH: flow_through.build,
    Archetype.U_FLOW: u_flow.build,
    Archetype.L_FLOW: l_flow.build,
    Archetype.CENTRAL_CORRIDOR: central_corridor.build,
    Archetype.ZONE_BASED: zone_based.build,
    Archetype.FISHBONE: fishbone.build,
}


class LayoutGenerationError(Exception):
    def __init__(self, reason: str, stage: str, seed: int, parameters: dict | None = None):
        self.reason = reason
        self.stage = stage
        self.seed = seed
        self.parameters = parameters or {}
        super().__init__(f"[seed={seed}, stage={stage}] {reason}")


@dataclass
class GeneratedLayout:
    config: LayoutConfig
    result: LayoutBuildResult
    graph: nx.Graph
    metrics: object
    validation: ValidationResult
    attempts: int = 1


def _build_one(seed: int, cfg: LayoutConfig) -> tuple[LayoutBuildResult, nx.Graph, ValidationResult, object]:
    builder = _ARCHETYPE_BUILDERS.get(cfg.warehouse.archetype)
    if builder is None:
        raise LayoutGenerationError(f"no builder registered for archetype {cfg.warehouse.archetype}", "dispatch", seed)
    rng = np.random.default_rng(seed)
    result = builder(rng, cfg)
    graph = build_navigation_graph(result)
    validation = validate_layout(cfg, result, graph)
    metrics = compute_metrics(graph, cfg.storage.storage_density, cfg.warehouse.aspect_ratio)
    return result, graph, validation, metrics


def generate_layout(
    seed: int,
    overrides: SamplingOverrides | None = None,
    max_attempts: int = 25,
) -> GeneratedLayout:
    overrides = overrides or SamplingOverrides()
    cfg = sample_config(seed, overrides)

    last_validation: ValidationResult | None = None
    for attempt in range(1, max_attempts + 1):
        result, graph, validation, metrics = _build_one(seed + attempt - 1, cfg)
        last_validation = validation
        if validation.valid:
            return GeneratedLayout(config=cfg, result=result, graph=graph, metrics=metrics, validation=validation, attempts=attempt)

        tags = validation.resample_tags
        # Offset well clear of the plausible direct-seed range (0 * k +
        # attempt would otherwise collapse to just `attempt`, colliding
        # with any other request's small original seed — caught by
        # tests/test_generation.py::test_batch_unique_layout_ids).
        resample_seed = (seed + 1_000_000) * 1_000_003 + attempt
        if "warehouse" in tags:
            cfg = sample_config(resample_seed, overrides)
        else:
            cfg = _resample_subsections(resample_seed, cfg, tags, overrides)

    raise LayoutGenerationError(
        reason=f"exceeded {max_attempts} generation attempts; last failures={last_validation.failures if last_validation else []}",
        stage="validate",
        seed=seed,
        parameters={"archetype": overrides.archetype.value if overrides.archetype else None},
    )


def _resample_subsections(seed: int, cfg: LayoutConfig, tags: set[str], overrides: SamplingOverrides) -> LayoutConfig:
    """Re-sample only the tagged subsections by pinning everything else
    via overrides derived from the current config, then re-sampling fresh
    with a new seed — cheaper than a full re-roll when the failure is
    local (e.g. just the aisle widths), while still guaranteeing a
    genuinely different draw for the failing subsection."""
    new_overrides = SamplingOverrides(
        scale_class=overrides.scale_class or cfg.warehouse.scale_class,
        industry_type=overrides.industry_type or cfg.warehouse.industry_type,
        archetype=overrides.archetype or cfg.warehouse.archetype,
        irregularity_level=overrides.irregularity_level if overrides.irregularity_level is not None else (
            cfg.diversity_controls.irregularity_level if "diversity_controls" not in tags else None
        ),
        dock_wall=overrides.dock_wall or cfg.structural_constraints.dock_wall,
    )
    return sample_config(seed, new_overrides)
