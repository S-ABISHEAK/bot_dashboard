"""Typed configuration schema for the warehouse layout generator.

Mirrors Section J of the FleetNet warehouse-layout research spec. Every
field is documented with: type, units (where applicable), valid range,
and whether it is FIXED (never sampled), SAMPLED (drawn from a
distribution when not pinned by the caller), CONDITIONAL (its
distribution depends on another field, e.g. industry_type), or DERIVED
(computed after generation, not settable by the caller).

These models are the single source of truth for what a config *can* say;
``generation.sampling`` is responsible for filling in anything left
unset before generation runs, and ``generation.generator`` is the only
code that mutates a config subsection during resample-on-reject.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleetnet_layout.config.enums import (
    AisleWidthClass,
    Archetype,
    DockWall,
    IndustryType,
    RackOrientation,
    RackType,
    ScaleClass,
    ZoneType,
)


class Polygon2D(BaseModel):
    """A simple closed polygon as a list of (x, y) vertices in meters."""

    model_config = ConfigDict(frozen=True)

    points: tuple[tuple[float, float], ...] = Field(
        ..., min_length=3, description="Ordered polygon vertices, meters, world frame."
    )


class WarehouseConfig(BaseModel):
    """Top-level shell parameters. FIXED once sampled: define the coordinate frame."""

    model_config = ConfigDict(frozen=True)

    seed: int = Field(..., description="FIXED. RNG seed; identical seed+config reproduces the identical layout.")
    scale_class: ScaleClass = Field(..., description="FIXED/SAMPLED. Governs the footprint/aisle/zone/dock scaffolds of Section G.")
    industry_type: IndustryType = Field(..., description="FIXED/SAMPLED. Conditions storage density, aisle width, rack type distributions (Section I).")
    archetype: Archetype = Field(..., description="FIXED/SAMPLED. Selects which archetypes.* builder generates the layout.")
    length_m: float = Field(..., gt=0, description="FIXED/SAMPLED. Building footprint length, meters, log-normal conditioned on scale_class.")
    width_m: float = Field(..., gt=0, description="FIXED/SAMPLED. Building footprint width, meters.")
    clear_height_m: float = Field(6.0, gt=0, description="SAMPLED. Clear ceiling height, meters; ~6-12m single-level, higher for AS/RS. Metadata only in 2D generation.")

    @property
    def area_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def aspect_ratio(self) -> float:
        return max(self.length_m, self.width_m) / max(min(self.length_m, self.width_m), 1e-9)


class StructuralConstraintsConfig(BaseModel):
    """FIXED/SAMPLED structural realities the generator must build around (Section H)."""

    model_config = ConfigDict(frozen=True)

    column_grid_spacing_m: Optional[float] = Field(
        None, gt=0, description="SAMPLED. Structural column grid spacing, meters (~10-12m typical). None disables columns."
    )
    dock_wall: DockWall = Field(DockWall.SOUTH, description="FIXED/SAMPLED. Primary wall docks are placed against; archetype-dependent for the second wall (u/l/flow_through).")
    fire_lane_width_m: float = Field(3.0, gt=0, description="FIXED. Minimum width reserved for fire lanes/egress corridors, meters.")
    fixed_exclusion_zones: tuple[Polygon2D, ...] = Field(
        default=(), description="SAMPLED. Additional fixed exclusion polygons (utility rooms, machinery) stamped onto the layout by the subtractive constraint layer."
    )


class StorageConfig(BaseModel):
    """SAMPLED/CONDITIONAL storage/rack parameters (Section D, J)."""

    model_config = ConfigDict(frozen=True)

    block_count: int = Field(..., ge=1, description="SAMPLED. Number of independent storage blocks; Poisson/normal conditioned on footprint (Section G bands).")
    rack_type: RackType = Field(RackType.SELECTIVE, description="CONDITIONAL. Dominant rack type; industry-biased categorical (Section I).")
    rack_row_count: int = Field(..., ge=1, description="SAMPLED. Total rack rows across all blocks.")
    rack_orientation: RackOrientation = Field(RackOrientation.PERPENDICULAR_TO_DOCK, description="SAMPLED/FIXED. Rack row orientation relative to the dock wall.")
    storage_density: float = Field(..., ge=0.0, le=1.0, description="CONDITIONAL. Fraction of footprint under racking; Beta distribution conditioned on industry_type.")


class AislesConfig(BaseModel):
    """SAMPLED aisle-network parameters (Section C, J)."""

    model_config = ConfigDict(frozen=True)

    main_count: int = Field(..., ge=1, description="SAMPLED. Count of main (wide, two-way-capable) aisles.")
    main_width_class: AisleWidthClass = Field(AisleWidthClass.STANDARD, description="SAMPLED/CONDITIONAL. Width class for main aisles.")
    secondary_count: int = Field(..., ge=0, description="SAMPLED. Count of secondary/picking aisles.")
    secondary_width_class: AisleWidthClass = Field(AisleWidthClass.NARROW, description="SAMPLED/CONDITIONAL. Width class for secondary aisles.")
    cross_aisle_interval_m: float = Field(..., gt=0, description="SAMPLED. Distance between cross-aisles along a main/secondary aisle, meters; caps max in-aisle travel distance.")
    one_way_ratio: float = Field(0.0, ge=0.0, le=1.0, description="SAMPLED. Fraction of eligible (narrow/VNA) aisles assigned one-way directionality.")


class ZoneSpec(BaseModel):
    """One operational zone's placement hint and target area."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(True, description="FIXED/SAMPLED. Small warehouses may disable/merge a zone (Section A).")
    area_m2: float = Field(..., gt=0, description="SAMPLED. Target zone footprint area, square meters.")
    position_hint: Optional[str] = Field(
        None, description="DERIVED at generation time from archetype + dock_wall; not user-set in normal sampling."
    )


class ZonesConfig(BaseModel):
    """SAMPLED operational-zone parameters (Section P, J)."""

    model_config = ConfigDict(frozen=True)

    receiving: ZoneSpec
    shipping: ZoneSpec
    staging: ZoneSpec
    picking: ZoneSpec
    packing: ZoneSpec
    returns: ZoneSpec
    charging: ZoneSpec
    office: ZoneSpec


class ConstraintsConfig(BaseModel):
    """FIXED hard validation-gate parameters (Section L, V)."""

    model_config = ConfigDict(frozen=True)

    min_clearance_m: float = Field(0.15, gt=0, description="FIXED. Minimum clearance beyond equipment operating width, meters (Section F).")
    max_dead_end_length_m: float = Field(40.0, gt=0, description="SAMPLED/CONDITIONAL. Longest permitted dead-end aisle segment, meters; generation.sampling ties the default to cross_aisle_interval_m so it scales with the generated aisle geometry rather than a single fixed constant.")
    require_full_connectivity: bool = Field(True, description="FIXED. Every storage/zone/dock node must be graph-reachable from every other.")
    require_dual_egress_paths: bool = Field(
        False,
        description=(
            "FIXED, opt-in. Deepest interior nodes need >=2 independent graph paths to "
            "designated exits. KNOWN LIMITATION (v1): this package models only the "
            "picking-aisle graph, not a separate emergency-egress corridor system, so "
            "single-block/no-interior-cross-aisle layouts are structurally tree-shaped "
            "(zero path redundancy anywhere) and can never satisfy this — defaulting to "
            "False avoids near-universal rejection for small/simple archetypes. Callers "
            "generating multi-block grid/zone_based layouts specifically for redundancy "
            "analysis can opt back in."
        ),
    )


class DiversityControlsConfig(BaseModel):
    """SAMPLED knobs controlling generated-instance variety (Section P, J)."""

    model_config = ConfigDict(frozen=True)

    irregularity_level: float = Field(0.0, ge=0.0, le=1.0, description="SAMPLED. Beta-skewed-low. Density/severity of the subtractive constraint layer (columns, exclusions, seams).")
    zone_arrangement_variant: int = Field(0, ge=0, description="SAMPLED. Tie-breaking seed for symmetric zone-placement choices (which side of a symmetric layout).")


class LayoutConfig(BaseModel):
    """The complete, validated top-level configuration for one generation run.

    This is the object ``generation.generator.WarehouseGenerator`` consumes.
    An instance is always fully specified (no field left to sample) —
    ``generation.sampling.sample_config`` is what produces one of these
    from just a seed plus optional pinned fields.
    """

    model_config = ConfigDict(frozen=True)

    warehouse: WarehouseConfig
    structural_constraints: StructuralConstraintsConfig
    storage: StorageConfig
    aisles: AislesConfig
    zones: ZonesConfig
    constraints: ConstraintsConfig
    diversity_controls: DiversityControlsConfig

    @model_validator(mode="after")
    def _check_storage_area_feasible(self) -> "LayoutConfig":
        footprint = self.warehouse.area_m2
        if self.storage.storage_density * footprint > footprint:
            raise ValueError("storage_density implies more storage area than the footprint provides")
        return self
