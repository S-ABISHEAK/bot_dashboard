"""storage.py's rows_per_block = rack_row_count // block_count must
never collapse to 1: fit_segments(target_count=1) returns a single
segment with no internal gap, so a block with exactly 1 row gets zero
secondary aisles. Downstream, fleetnet_sim's WorldBridge.rack_aisle_cells
would then be empty and picking tasks silently fall back to routing
through the raw picking-zone band instead of an aisle (see
core/task_generator.py::_cells_for). Floored at 2 so every block always
has >= 1 internal gap.
"""
from __future__ import annotations

import numpy as np

from fleetnet_layout.config.enums import AisleWidthClass, RackOrientation, RackType
from fleetnet_layout.config.schema import AislesConfig, StorageConfig
from fleetnet_layout.generation.storage import build_storage_field
from fleetnet_layout.geometry.primitives import Rect


def _build(block_count: int, rack_row_count: int):
    storage_cfg = StorageConfig(
        block_count=block_count,
        rack_type=RackType.SELECTIVE,
        rack_row_count=rack_row_count,
        rack_orientation=RackOrientation.PERPENDICULAR_TO_DOCK,
        storage_density=0.5,
    )
    aisles_cfg = AislesConfig(
        main_count=block_count,
        main_width_class=AisleWidthClass.STANDARD,
        secondary_count=rack_row_count,
        secondary_width_class=AisleWidthClass.NARROW,
        cross_aisle_interval_m=20.0,
        one_way_ratio=0.0,
    )
    rect = Rect(0.0, 0.0, 100.0, 60.0)
    rng = np.random.default_rng(0)
    return build_storage_field(rng, rect, storage_cfg, aisles_cfg, id_prefix="t0")


def test_rows_per_block_never_zeroes_out_secondary_aisles():
    # block_count == rack_row_count -> naive rows_per_block = 1 (the
    # exact case that used to zero out every block's secondary aisles).
    field = _build(block_count=10, rack_row_count=10)
    assert field.secondary_aisles, "expected at least one secondary aisle even when rack_row_count == block_count"


def test_rows_per_block_still_works_when_rows_exceed_blocks():
    field = _build(block_count=3, rack_row_count=30)
    assert field.secondary_aisles
