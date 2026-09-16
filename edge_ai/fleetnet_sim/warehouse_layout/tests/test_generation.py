from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.geometry.operations import any_overlap, within_boundary


def test_generate_small_grid_is_valid():
    layout = generate_layout(1, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    assert layout.validation.valid
    assert layout.graph.number_of_nodes() > 0


def test_no_illegal_overlaps_across_seeds():
    for seed in range(5):
        layout = generate_layout(seed, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
        non_aisle = layout.result.racks + layout.result.zones + layout.result.all_exclusions
        assert any_overlap(non_aisle) == []


def test_geometry_within_footprint():
    layout = generate_layout(2, SamplingOverrides(archetype=Archetype.U_FLOW, scale_class=ScaleClass.MEDIUM))
    fp = layout.result.footprint.to_polygon()
    all_objects = layout.result.racks + layout.result.zones + layout.result.all_aisles + layout.result.docks
    for obj in all_objects:
        assert within_boundary(obj.polygon, fp), obj.id


def test_irregularity_changes_geometry():
    low = generate_layout(3, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.MEDIUM, irregularity_level=0.0))
    high = generate_layout(3, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.MEDIUM, irregularity_level=0.9))
    assert len(low.result.columns) <= len(high.result.columns)


def test_batch_unique_layout_ids():
    ids = set()
    for seed in range(10):
        layout = generate_layout(seed, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
        from fleetnet_layout.serialization.json_io import compute_layout_id

        ids.add(compute_layout_id(layout.config))
    assert len(ids) == 10
