"""Generation scaffolds and engineering-default constants.

These are sampling *scaffolds*, not physical laws (Section G explicitly
warns against treating them as hard classifications). Every value here
is meant to be read by ``generation.sampling`` / ``config.distributions``,
never hardcoded directly into an archetype builder.
"""
from __future__ import annotations

from dataclasses import dataclass

from fleetnet_layout.config.enums import AisleWidthClass, Archetype, IndustryType, ScaleClass


@dataclass(frozen=True)
class ScaleBand:
    area_m2: tuple[float, float]
    block_count: tuple[int, int]
    aisle_count: tuple[int, int]
    zone_count: tuple[int, int]
    dock_count: tuple[int, int]


SCALE_BANDS: dict[ScaleClass, ScaleBand] = {
    ScaleClass.SMALL: ScaleBand((1_000, 5_000), (1, 3), (5, 15), (3, 5), (1, 4)),
    ScaleClass.MEDIUM: ScaleBand((5_000, 20_000), (3, 8), (15, 40), (5, 8), (4, 15)),
    ScaleClass.LARGE: ScaleBand((20_000, 100_000), (8, 20), (40, 120), (7, 10), (15, 60)),
    ScaleClass.VERY_LARGE: ScaleBand((100_000, 250_000), (20, 32), (120, 200), (8, 12), (60, 100)),
}

# Aisle width class bands, meters (Section C).
AISLE_WIDTH_BANDS_M: dict[AisleWidthClass, tuple[float, float]] = {
    AisleWidthClass.NARROW_VNA: (1.5, 1.8),
    AisleWidthClass.NARROW: (2.2, 2.7),
    AisleWidthClass.STANDARD: (3.0, 3.5),
    AisleWidthClass.WIDE: (3.6, 4.5),
}

# Pallet/rack engineering defaults (Section N). Configurable, not universal.
PALLET_FOOTPRINT_M = (1.2, 1.0)  # 48x40 in, approx meters
RACK_BAY_WIDTH_M = 2.6  # ~96in beam for two pallets + uprights
RACK_ROW_DEPTH_M = 2.3  # single-deep, back-to-back pair total depth
SAFETY_CLEARANCE_M = 0.2

DOCK_DOOR_SPACING_M = 4.0
DOCK_AREA_PER_DOOR_M2 = 10_000 / 10.7639  # ~1 door / 10,000 sq ft -> m^2/door

# Industry-conditioned biases: multiplicative/additive nudges applied on
# top of the base distributions in ``config.distributions``. Keys are a
# subset of the fields they bias; values are (shift, note) where "shift"
# is interpreted per-distribution (see distributions.py call sites).
INDUSTRY_STORAGE_DENSITY_BETA: dict[IndustryType, tuple[float, float]] = {
    # (alpha, beta) shape params -> mode = (alpha-1)/(alpha+beta-2)
    IndustryType.ECOMMERCE: (6.0, 2.5),
    IndustryType.PARCEL: (5.0, 3.0),
    IndustryType.ELECTRONICS: (5.5, 3.0),
    IndustryType.RETAIL: (4.0, 3.0),
    IndustryType.GROCERY: (4.0, 3.5),
    IndustryType.GENERAL_3PL: (3.5, 3.5),
    IndustryType.PHARMA: (4.0, 4.0),
    IndustryType.MANUFACTURING: (2.5, 5.0),
    IndustryType.AUTOMOTIVE: (2.5, 5.5),
    IndustryType.COLD_STORAGE: (2.0, 5.0),
}

INDUSTRY_AISLE_WIDTH_BIAS: dict[IndustryType, dict[AisleWidthClass, float]] = {
    # relative weight nudge added to the categorical weights in distributions.py
    IndustryType.ECOMMERCE: {AisleWidthClass.NARROW_VNA: 2.0, AisleWidthClass.NARROW: 1.5},
    IndustryType.PARCEL: {AisleWidthClass.NARROW: 1.5, AisleWidthClass.STANDARD: 1.2},
    IndustryType.COLD_STORAGE: {AisleWidthClass.STANDARD: 1.5, AisleWidthClass.WIDE: 1.5},
    IndustryType.MANUFACTURING: {AisleWidthClass.WIDE: 2.0, AisleWidthClass.STANDARD: 1.3},
    IndustryType.AUTOMOTIVE: {AisleWidthClass.WIDE: 2.0},
}

ARCHETYPE_WEIGHTS: dict[Archetype, float] = {
    Archetype.GRID: 0.28,
    Archetype.FLOW_THROUGH: 0.20,
    Archetype.U_FLOW: 0.16,
    Archetype.CENTRAL_CORRIDOR: 0.14,
    Archetype.ZONE_BASED: 0.12,
    Archetype.L_FLOW: 0.07,
    Archetype.FISHBONE: 0.03,
}

INDUSTRY_WEIGHTS: dict[IndustryType, float] = {
    IndustryType.ECOMMERCE: 0.18,
    IndustryType.GENERAL_3PL: 0.14,
    IndustryType.RETAIL: 0.12,
    IndustryType.GROCERY: 0.10,
    IndustryType.PARCEL: 0.10,
    IndustryType.MANUFACTURING: 0.10,
    IndustryType.ELECTRONICS: 0.08,
    IndustryType.AUTOMOTIVE: 0.07,
    IndustryType.COLD_STORAGE: 0.06,
    IndustryType.PHARMA: 0.05,
}

# Default minimum zone area as a fraction of footprint, before scale/industry
# adjustment; used when a zone is enabled but no explicit area was pinned.
DEFAULT_ZONE_AREA_FRACTION: dict[str, float] = {
    "receiving": 0.04,
    "shipping": 0.04,
    "staging": 0.05,
    "picking": 0.03,
    "packing": 0.03,
    "returns": 0.02,
    "charging": 0.015,
    "office": 0.01,
}
