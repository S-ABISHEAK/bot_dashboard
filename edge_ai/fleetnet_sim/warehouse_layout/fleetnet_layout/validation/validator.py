"""Validation pipeline orchestrator (Section L/V): the hard gate every
generated layout must pass before being emitted as a valid instance.

Runs checks in the pipeline order Section L specifies: geometric overlap
-> boundary -> graph connectivity -> clearance -> dead-end length ->
one-way consistency -> zone reachability -> dual egress. Each failure is
tagged with the config subsection most likely responsible, so
``generation.generator`` can resample just that subsection instead of
the whole layout (Section L's efficiency requirement).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.validation import clearance, connectivity, egress, geometry, reachability

# Which config subsection a failure-code prefix should trigger a
# resample of. "warehouse" means the whole layout must be re-rolled
# (a footprint/archetype-level problem, not a local one).
_FAILURE_TAG_MAP = {
    "overlap": "storage",
    "out_of_bounds": "storage",
    "connectivity": "warehouse",
    "zone_unreachable": "zones",
    "zone_no_aisle_access": "zones",
    "one_way_inconsistent": "aisles",
    "sub_minimum_clearance": "aisles",
    "dead_end_too_long": "aisles",
    "egress_unreachable": "warehouse",
    "insufficient_egress_paths": "warehouse",
    "egress": "warehouse",
}


@dataclass
class ValidationResult:
    valid: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def resample_tags(self) -> set[str]:
        tags = set()
        for f in self.failures:
            prefix = f.split(":", 1)[0]
            tags.add(_FAILURE_TAG_MAP.get(prefix, "warehouse"))
        return tags

    def checks_summary(self) -> dict[str, bool]:
        by_tag: dict[str, list[str]] = {}
        for f in self.failures:
            prefix = f.split(":", 1)[0]
            by_tag.setdefault(prefix, []).append(f)
        return {k: False for k in by_tag} if by_tag else {"all": True}


def validate_layout(cfg: LayoutConfig, result: LayoutBuildResult, graph: nx.Graph) -> ValidationResult:
    failures: list[str] = []

    failures += geometry.check_no_illegal_overlap(result)
    failures += geometry.check_within_boundary(result)

    if cfg.constraints.require_full_connectivity:
        failures += connectivity.check_full_connectivity(graph)
        failures += connectivity.check_zone_reachability(graph)
        failures += reachability.check_zone_has_aisle_access(result)

    failures += clearance.check_min_clearance(result, cfg.constraints.min_clearance_m)
    failures += connectivity.check_dead_end_length(graph, cfg.constraints.max_dead_end_length_m)
    failures += connectivity.check_one_way_consistency(graph)

    if cfg.constraints.require_dual_egress_paths and not any(f.startswith("connectivity") for f in failures):
        failures += egress.check_dual_egress(graph)

    return ValidationResult(valid=len(failures) == 0, failures=failures)
