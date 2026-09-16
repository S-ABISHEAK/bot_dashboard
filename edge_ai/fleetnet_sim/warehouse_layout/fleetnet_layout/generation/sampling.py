"""Seed -> fully-sampled LayoutConfig (Section I/K).

``sample_config`` is the only place that turns a bare seed (plus any
caller-pinned fields) into a complete, schema-valid ``LayoutConfig``. It
owns the single ``numpy.random.Generator`` for the whole run and applies
the industry-conditioned biases from Section I (e-commerce -> narrower
aisles/higher density, cold storage -> simpler/wider, manufacturing ->
bulk/cantilever/lower density).

``generation.generator.WarehouseGenerator`` re-invokes the relevant
``resample_*`` helper (not this whole function) when validation rejects
a layout and tags the failure to a specific config subsection.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fleetnet_layout.config.defaults import (
    AISLE_WIDTH_BANDS_M,
    ARCHETYPE_WEIGHTS,
    DEFAULT_ZONE_AREA_FRACTION,
    INDUSTRY_AISLE_WIDTH_BIAS,
    INDUSTRY_STORAGE_DENSITY_BETA,
    INDUSTRY_WEIGHTS,
    SCALE_BANDS,
)
from fleetnet_layout.config.distributions import (
    beta_in_unit,
    beta_skewed_low,
    log_normal_in_range,
    poisson_in_range,
    truncated_normal,
    weighted_categorical,
)
from fleetnet_layout.config.enums import (
    AisleWidthClass,
    Archetype,
    DockWall,
    IndustryType,
    RackOrientation,
    RackType,
    ScaleClass,
)
from fleetnet_layout.config.schema import (
    AislesConfig,
    ConstraintsConfig,
    DiversityControlsConfig,
    LayoutConfig,
    StorageConfig,
    StructuralConstraintsConfig,
    WarehouseConfig,
    ZoneSpec,
    ZonesConfig,
)

# Industry -> dominant rack type bias (Section I's conditional rules).
_INDUSTRY_RACK_TYPE: dict[IndustryType, RackType] = {
    IndustryType.ECOMMERCE: RackType.SHELVING,
    IndustryType.PARCEL: RackType.SHELVING,
    IndustryType.ELECTRONICS: RackType.SHELVING,
    IndustryType.RETAIL: RackType.SELECTIVE,
    IndustryType.GROCERY: RackType.SELECTIVE,
    IndustryType.GENERAL_3PL: RackType.SELECTIVE,
    IndustryType.PHARMA: RackType.SELECTIVE,
    IndustryType.COLD_STORAGE: RackType.DRIVE_IN,
    IndustryType.MANUFACTURING: RackType.CANTILEVER,
    IndustryType.AUTOMOTIVE: RackType.CANTILEVER,
}

# Industry -> archetype irregularity bias multiplier (cold storage stays
# simple/rectangular per Section I; retrofit-prone industries run higher).
_INDUSTRY_IRREGULARITY_BIAS: dict[IndustryType, float] = {
    IndustryType.COLD_STORAGE: 0.4,
    IndustryType.PHARMA: 0.6,
    IndustryType.MANUFACTURING: 1.3,
    IndustryType.AUTOMOTIVE: 1.3,
    IndustryType.GENERAL_3PL: 1.2,
}


@dataclass
class SamplingOverrides:
    """Caller-pinned fields; anything left as None is sampled."""

    scale_class: ScaleClass | None = None
    industry_type: IndustryType | None = None
    archetype: Archetype | None = None
    irregularity_level: float | None = None
    dock_wall: DockWall | None = None


def _sample_aisle_width_class(
    rng: np.random.Generator, industry: IndustryType, candidates: list[AisleWidthClass], base_weight: float = 1.0
) -> AisleWidthClass:
    bias = INDUSTRY_AISLE_WIDTH_BIAS.get(industry, {})
    weights = {c: base_weight + bias.get(c, 0.0) for c in candidates}
    return weighted_categorical(rng, weights)


def sample_config(seed: int, overrides: SamplingOverrides | None = None) -> LayoutConfig:
    overrides = overrides or SamplingOverrides()
    rng = np.random.default_rng(seed)

    scale_class = overrides.scale_class or weighted_categorical(
        rng, {s: 1.0 for s in ScaleClass}
    )
    industry = overrides.industry_type or weighted_categorical(rng, INDUSTRY_WEIGHTS)
    archetype = overrides.archetype or weighted_categorical(rng, ARCHETYPE_WEIGHTS)
    # NOTE: grid/flow_through/u_flow's zone/dock packers only support
    # horizontal bands (north/south walls); east/west is reserved for
    # l_flow's corner-zone logic (Section B), which rotates the frame
    # itself rather than reusing pack_zone_band directly. Restricting the
    # sample here (rather than in the archetype builders) keeps every
    # Phase-1/2 orthogonal archetype's zone geometry always in-bounds.
    dock_wall = overrides.dock_wall or weighted_categorical(rng, {DockWall.SOUTH: 0.6, DockWall.NORTH: 0.4})

    band = SCALE_BANDS[scale_class]

    footprint_area = log_normal_in_range(rng, *band.area_m2)

    # Aisle/block counts are otherwise sampled from a fixed per-scale-class
    # range regardless of where footprint_area actually landed within that
    # class's own area_m2 span -- a very_large warehouse at 250,000 m² would
    # get the same aisle population as one at 100,000 m², just stretched
    # thinner/longer. Scale the count ranges by sqrt(area / band-geometric-
    # mean) (aisle *density* ~ linear dimension ~ sqrt(area)), clamped to a
    # safe +/-70% band so this never pushes counts outside validated
    # territory.
    band_area_mid = (band.area_m2[0] * band.area_m2[1]) ** 0.5
    area_scale = float(np.clip((footprint_area / band_area_mid) ** 0.5, 0.6, 1.7))

    def _scaled_range(count_range: tuple[int, int], min_low: int = 1) -> tuple[int, int]:
        lo, hi = count_range
        return max(min_low, round(lo * area_scale)), max(min_low + 1, round(hi * area_scale))

    scaled_block_count = _scaled_range(band.block_count)
    scaled_aisle_count = _scaled_range(band.aisle_count, min_low=2)

    aspect = truncated_normal(rng, 1.1, 2.2, mean=1.5, rel_sigma=0.25)
    width_m = float(np.sqrt(footprint_area / aspect))
    length_m = footprint_area / width_m

    clear_height = truncated_normal(rng, 6.0, 12.0, mean=8.0)

    warehouse = WarehouseConfig(
        seed=seed,
        scale_class=scale_class,
        industry_type=industry,
        archetype=archetype,
        length_m=round(length_m, 2),
        width_m=round(width_m, 2),
        clear_height_m=round(clear_height, 2),
    )

    column_spacing = truncated_normal(rng, 9.0, 13.0, mean=11.0)
    structural = StructuralConstraintsConfig(
        column_grid_spacing_m=column_spacing,
        dock_wall=dock_wall,
        fire_lane_width_m=3.0,
    )

    alpha, beta = INDUSTRY_STORAGE_DENSITY_BETA.get(industry, (3.5, 3.5))
    storage_density = beta_in_unit(rng, alpha, beta)
    # Beta mode can sit very high; clamp to a sane build envelope.
    storage_density = float(np.clip(storage_density, 0.1, 0.75))

    block_count = poisson_in_range(rng, *scaled_block_count)
    rack_row_count = poisson_in_range(
        rng, max(block_count, 2), max(scaled_aisle_count[1] // 2, block_count + 2),
        mean=scaled_aisle_count[0] * 0.6,
    )
    rack_type = _INDUSTRY_RACK_TYPE.get(industry, RackType.SELECTIVE)
    rack_orientation = weighted_categorical(
        rng, {RackOrientation.PERPENDICULAR_TO_DOCK: 0.7, RackOrientation.PARALLEL_TO_DOCK: 0.3}
    )
    storage = StorageConfig(
        block_count=block_count,
        rack_type=rack_type,
        rack_row_count=rack_row_count,
        rack_orientation=rack_orientation,
        storage_density=round(storage_density, 3),
    )

    # main_count's mean=2 is deliberately left unscaled here: main aisles are
    # physically wider load-bearing corridors, and bumping the Poisson mean
    # is a separate, higher-risk behavioral change not needed to fix aisle
    # density -- only its upper bound scales via scaled_aisle_count[0].
    main_count = max(1, poisson_in_range(rng, 1, max(2, scaled_aisle_count[0] // 5), mean=2))
    secondary_count = poisson_in_range(
        rng, *scaled_aisle_count, mean=(scaled_aisle_count[0] + scaled_aisle_count[1]) / 2
    )
    main_width_class = _sample_aisle_width_class(
        rng, industry, [AisleWidthClass.STANDARD, AisleWidthClass.WIDE], base_weight=1.0
    )
    secondary_width_class = _sample_aisle_width_class(
        rng, industry, [AisleWidthClass.NARROW_VNA, AisleWidthClass.NARROW, AisleWidthClass.STANDARD], base_weight=1.0
    )
    cross_interval = truncated_normal(rng, 15.0, 40.0, mean=25.0)
    one_way_ratio = float(np.clip(beta_in_unit(rng, 2.0, 4.0), 0.0, 0.6))

    aisles = AislesConfig(
        main_count=main_count,
        main_width_class=main_width_class,
        secondary_count=max(secondary_count, 2),
        secondary_width_class=secondary_width_class,
        cross_aisle_interval_m=round(cross_interval, 2),
        one_way_ratio=round(one_way_ratio, 3),
    )

    is_small = scale_class == ScaleClass.SMALL
    zone_specs: dict[str, ZoneSpec] = {}
    for name, frac in DEFAULT_ZONE_AREA_FRACTION.items():
        area = max(footprint_area * frac, 15.0)
        enabled = True
        if is_small and name in ("returns", "office"):
            enabled = bool(rng.random() > 0.4)
        zone_specs[name] = ZoneSpec(enabled=enabled, area_m2=round(area, 1))
    zones = ZonesConfig(**zone_specs)

    # Tied to cross_aisle_interval_m (rather than one fixed constant) so
    # the dead-end limit scales with the generated aisle geometry: a
    # field's mandatory front/back spine (generation.storage) can
    # legitimately run most of the block axis before its first junction
    # when row counts are low, and that's architecturally normal, not
    # invalid, for a small/simple layout.
    constraints = ConstraintsConfig(max_dead_end_length_m=max(40.0, aisles.cross_aisle_interval_m * 2.5))

    if overrides.irregularity_level is not None:
        irregularity = overrides.irregularity_level
    else:
        irregularity = beta_skewed_low(rng) * _INDUSTRY_IRREGULARITY_BIAS.get(industry, 1.0)
        irregularity = float(np.clip(irregularity, 0.0, 1.0))
    diversity = DiversityControlsConfig(
        irregularity_level=round(irregularity, 3),
        zone_arrangement_variant=int(rng.integers(0, 4)),
    )

    return LayoutConfig(
        warehouse=warehouse,
        structural_constraints=structural,
        storage=storage,
        aisles=aisles,
        zones=zones,
        constraints=constraints,
        diversity_controls=diversity,
    )


def aisle_width_m(rng: np.random.Generator, width_class: AisleWidthClass) -> float:
    low, high = AISLE_WIDTH_BANDS_M[width_class]
    return truncated_normal(rng, low, high)
