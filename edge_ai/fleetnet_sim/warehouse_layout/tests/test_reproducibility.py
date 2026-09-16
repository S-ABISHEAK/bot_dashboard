from fleetnet_layout.config.enums import Archetype
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import compute_layout_id, to_json_dict


def test_same_seed_same_config_reproduces_identical_layout():
    overrides = SamplingOverrides(archetype=Archetype.GRID)
    a = generate_layout(42, overrides)
    b = generate_layout(42, overrides)

    assert a.config == b.config
    assert compute_layout_id(a.config) == compute_layout_id(b.config)

    ja = to_json_dict(a.config, a.result, a.graph, a.metrics, a.validation)
    jb = to_json_dict(b.config, b.result, b.graph, b.metrics, b.validation)
    assert ja["geometry"]["racks"] == jb["geometry"]["racks"]
    assert ja["geometry"]["aisles"] == jb["geometry"]["aisles"]
    assert ja["navigation_graph"] == jb["navigation_graph"]


def test_different_seeds_differ():
    overrides = SamplingOverrides(archetype=Archetype.GRID)
    a = generate_layout(1, overrides)
    b = generate_layout(2, overrides)
    assert a.config != b.config
