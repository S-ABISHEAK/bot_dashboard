"""Batch report builder: rejection reasons + the diversity report,
consumed by the CLI's ``batch``/``report`` subcommands (Section AN).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from fleetnet_layout.diversity.metrics import DiversityReport, compute_diversity
from fleetnet_layout.generation.generator import GeneratedLayout


@dataclass
class BatchReport:
    valid_count: int
    rejected_count: int
    rejection_reasons: Counter
    diversity: DiversityReport | None

    def to_dict(self) -> dict:
        return {
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "rejection_reasons": dict(self.rejection_reasons),
            "diversity": self.diversity.to_dict() if self.diversity else None,
        }

    def write(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


def build_batch_report(successes: list[GeneratedLayout], rejection_log: list[str]) -> BatchReport:
    reasons = Counter()
    for entry in rejection_log:
        reasons[entry.split(":", 1)[0]] += 1
    diversity = compute_diversity(successes) if successes else None
    return BatchReport(
        valid_count=len(successes),
        rejected_count=len(rejection_log),
        rejection_reasons=reasons,
        diversity=diversity,
    )
