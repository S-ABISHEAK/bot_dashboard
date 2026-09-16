"""Seeded, non-uniform sampling primitives (Section K).

Every function takes an explicit ``numpy.random.Generator`` — there is no
module-level RNG anywhere in this package. This is what makes seed+config
reproducibility structural rather than incidental (see the plan's
"Determinism" design decision): a single Generator is created once per
generation call in ``generation.sampling`` and threaded through every
call below.
"""
from __future__ import annotations

from typing import Mapping, Sequence, TypeVar

import numpy as np

T = TypeVar("T")


def weighted_categorical(rng: np.random.Generator, weights: Mapping[T, float]) -> T:
    """Weighted-categorical draw (Section K). Never use plain uniform choice
    for a semantically meaningful categorical (archetype, industry, rack type)."""
    keys = list(weights.keys())
    w = np.array([weights[k] for k in keys], dtype=float)
    w = w / w.sum()
    idx = rng.choice(len(keys), p=w)
    return keys[idx]


def uniform_tiebreak(rng: np.random.Generator, options: Sequence[T]) -> T:
    """Plain uniform choice — reserved for symmetric tie-breaking only
    (e.g. which side of a symmetric layout an optional zone sits on),
    never for a dimension/count parameter (Section K)."""
    idx = rng.integers(0, len(options))
    return options[idx]


def log_normal_in_range(
    rng: np.random.Generator, low: float, high: float, skew: float = 0.55
) -> float:
    """Log-normal sample clipped to [low, high], mode biased toward the
    lower-middle of the range (facility sizes are right-skewed: many
    mid-size, few huge outliers)."""
    mid = (low + high) / 2.0
    mu = np.log(max(mid * (1 - 0.15), low * 1.01))
    val = rng.lognormal(mean=mu, sigma=skew)
    return float(np.clip(val, low, high))


def truncated_normal(
    rng: np.random.Generator, low: float, high: float, mean: float | None = None, rel_sigma: float = 0.12
) -> float:
    """Normal draw truncated (via resampling) to [low, high], clustered
    around ``mean`` (defaults to the band midpoint) — used for aisle
    widths within a class, which cluster near equipment-standard values."""
    if mean is None:
        mean = (low + high) / 2.0
    sigma = max((high - low) * rel_sigma, 1e-6)
    for _ in range(50):
        val = rng.normal(mean, sigma)
        if low <= val <= high:
            return float(val)
    return float(np.clip(mean, low, high))


def poisson_in_range(rng: np.random.Generator, low: int, high: int, mean: float | None = None) -> int:
    """Poisson count clamped to [low, high], centered near the band's
    implied mean (area-conditioned counts should cluster, not spread
    uniformly across the whole legal range)."""
    if mean is None:
        mean = (low + high) / 2.0
    for _ in range(50):
        val = int(rng.poisson(lam=max(mean, 0.1)))
        if low <= val <= high:
            return val
    return int(np.clip(round(mean), low, high))


def beta_in_unit(rng: np.random.Generator, alpha: float, beta: float) -> float:
    """Beta(alpha, beta) draw in [0, 1] — used for storage_density
    (industry-conditioned mode) and irregularity_level (skewed low)."""
    return float(rng.beta(alpha, beta))


def beta_skewed_low(rng: np.random.Generator, strength: float = 4.0) -> float:
    """Beta distribution skewed toward low values, for irregularity_level:
    most warehouses are mostly regular; heavy irregularity is a tail case."""
    return float(rng.beta(1.5, strength))
