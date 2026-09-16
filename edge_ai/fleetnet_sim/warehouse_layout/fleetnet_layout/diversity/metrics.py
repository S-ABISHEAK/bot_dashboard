"""Per-batch diversity measurement (Section P) — diversity is measured,
not assumed from randomized sampling.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from fleetnet_layout.generation.generator import GeneratedLayout


def shannon_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            ent -= p * math.log2(p)
    return ent


@dataclass
class DiversityReport:
    n: int
    scale_distribution: Counter
    archetype_distribution: Counter
    industry_distribution: Counter
    aspect_ratio: list[float] = field(default_factory=list)
    aisle_count: list[int] = field(default_factory=list)
    intersection_count: list[int] = field(default_factory=list)
    storage_density: list[float] = field(default_factory=list)
    bottleneck_count: list[int] = field(default_factory=list)
    irregularity_level: list[float] = field(default_factory=list)
    entropy: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        def stats(xs):
            if not xs:
                return {"min": None, "max": None, "mean": None}
            return {"min": min(xs), "max": max(xs), "mean": sum(xs) / len(xs)}

        return {
            "n": self.n,
            "scale_distribution": dict(self.scale_distribution),
            "archetype_distribution": dict(self.archetype_distribution),
            "industry_distribution": dict(self.industry_distribution),
            "aspect_ratio": stats(self.aspect_ratio),
            "aisle_count": stats(self.aisle_count),
            "intersection_count": stats(self.intersection_count),
            "storage_density": stats(self.storage_density),
            "bottleneck_count": stats(self.bottleneck_count),
            "irregularity_level": stats(self.irregularity_level),
            "entropy": self.entropy,
        }


def compute_diversity(layouts: list[GeneratedLayout]) -> DiversityReport:
    scale_c = Counter(l.config.warehouse.scale_class.value for l in layouts)
    arch_c = Counter(l.config.warehouse.archetype.value for l in layouts)
    ind_c = Counter(l.config.warehouse.industry_type.value for l in layouts)

    report = DiversityReport(
        n=len(layouts),
        scale_distribution=scale_c,
        archetype_distribution=arch_c,
        industry_distribution=ind_c,
        aspect_ratio=[l.config.warehouse.aspect_ratio for l in layouts],
        aisle_count=[l.metrics.aisle_count for l in layouts],
        intersection_count=[l.metrics.intersection_count for l in layouts],
        storage_density=[l.config.storage.storage_density for l in layouts],
        bottleneck_count=[len(l.metrics.bottleneck_candidates) for l in layouts],
        irregularity_level=[l.config.diversity_controls.irregularity_level for l in layouts],
    )
    report.entropy = {
        "scale_class": shannon_entropy(scale_c),
        "archetype": shannon_entropy(arch_c),
        "industry_type": shannon_entropy(ind_c),
    }
    return report
