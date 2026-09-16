import pytest
from pydantic import ValidationError

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


def _zones() -> ZonesConfig:
    return ZonesConfig(
        receiving=ZoneSpec(area_m2=100),
        shipping=ZoneSpec(area_m2=100),
        staging=ZoneSpec(area_m2=150),
        picking=ZoneSpec(area_m2=80),
        packing=ZoneSpec(area_m2=80),
        returns=ZoneSpec(area_m2=40),
        charging=ZoneSpec(area_m2=30),
        office=ZoneSpec(area_m2=20),
    )


def make_config(**overrides) -> LayoutConfig:
    base = dict(
        warehouse=WarehouseConfig(
            seed=1,
            scale_class=ScaleClass.SMALL,
            industry_type=IndustryType.ECOMMERCE,
            archetype=Archetype.GRID,
            length_m=60,
            width_m=40,
        ),
        structural_constraints=StructuralConstraintsConfig(dock_wall=DockWall.SOUTH),
        storage=StorageConfig(block_count=2, rack_row_count=8, storage_density=0.35, rack_type=RackType.SELECTIVE, rack_orientation=RackOrientation.PERPENDICULAR_TO_DOCK),
        aisles=AislesConfig(main_count=2, main_width_class=AisleWidthClass.STANDARD, secondary_count=6, secondary_width_class=AisleWidthClass.NARROW, cross_aisle_interval_m=20),
        zones=_zones(),
        constraints=ConstraintsConfig(),
        diversity_controls=DiversityControlsConfig(),
    )
    base.update(overrides)
    return LayoutConfig(**base)


def test_valid_config_builds():
    cfg = make_config()
    assert cfg.warehouse.area_m2 == 2400
    assert cfg.storage.storage_density == 0.35


def test_frozen_immutable():
    cfg = make_config()
    with pytest.raises(ValidationError):
        cfg.warehouse.seed = 2  # type: ignore[misc]


def test_negative_length_rejected():
    with pytest.raises(ValidationError):
        WarehouseConfig(
            seed=1,
            scale_class=ScaleClass.SMALL,
            industry_type=IndustryType.ECOMMERCE,
            archetype=Archetype.GRID,
            length_m=-10,
            width_m=40,
        )


def test_storage_density_out_of_range_rejected():
    with pytest.raises(ValidationError):
        StorageConfig(block_count=2, rack_row_count=8, storage_density=1.5, rack_type=RackType.SELECTIVE)


def test_one_way_ratio_bounds():
    with pytest.raises(ValidationError):
        AislesConfig(main_count=1, secondary_count=1, cross_aisle_interval_m=10, one_way_ratio=1.5)
