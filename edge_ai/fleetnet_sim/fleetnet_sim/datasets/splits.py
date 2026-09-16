"""Leakage-safe, run-level train/val/test split (Section 19: "never
randomly split adjacent rows from one trajectory"). A run_id is hashed
into a stable bucket so the same run always lands in the same split
across rebuilds, and every row from that run goes with it.
"""
from __future__ import annotations

import hashlib


def split_for_run(run_id: str, train: float = 0.7, val: float = 0.15) -> str:
    h = int(hashlib.sha256(run_id.encode()).hexdigest(), 16)
    frac = (h % 10_000) / 10_000.0
    if frac < train:
        return "train"
    if frac < train + val:
        return "val"
    return "test"
