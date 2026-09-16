from shapely.geometry import box

from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.geometry.primitives import GeoObject
from fleetnet_layout.validation.geometry import check_no_illegal_overlap
from fleetnet_layout.validation.validator import validate_layout


def test_validator_rejects_manual_overlap():
    layout = generate_layout(1, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    r0 = layout.result.racks[0]
    dupe = GeoObject(id="dupe_rack", kind="rack", polygon=r0.polygon, metadata={})
    layout.result.racks.append(dupe)
    failures = check_no_illegal_overlap(layout.result)
    assert any(f.startswith("overlap:") for f in failures)


def test_validate_layout_returns_failures_list():
    layout = generate_layout(2, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    result = validate_layout(layout.config, layout.result, layout.graph)
    assert result.valid
    assert result.failures == []


def test_resample_tags_present_on_failure():
    layout = generate_layout(3, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    r0 = layout.result.racks[0]
    dupe = GeoObject(id="dupe_rack2", kind="rack", polygon=r0.polygon, metadata={})
    layout.result.racks.append(dupe)
    from fleetnet_layout.validation.validator import validate_layout as vl

    result = vl(layout.config, layout.result, layout.graph)
    assert not result.valid
    assert "storage" in result.resample_tags
