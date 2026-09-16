import json

from fleetnet_layout.config.enums import Archetype
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import graph_from_json, to_json_dict


def test_json_round_trip_is_valid_json_and_graph_reloads():
    layout = generate_layout(9, SamplingOverrides(archetype=Archetype.GRID))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)

    # Must be plain-JSON-serializable (no numpy/enum/dataclass leakage).
    text = json.dumps(data)
    reloaded = json.loads(text)

    assert reloaded["schema_version"] == "1.0"
    assert reloaded["seed"] == 9
    assert reloaded["validation"]["valid"] is True
    assert len(reloaded["geometry"]["racks"]) == len(layout.result.racks)

    g = graph_from_json(reloaded)
    assert g.number_of_nodes() == layout.graph.number_of_nodes()
    assert g.number_of_edges() == layout.graph.number_of_edges()


def test_no_robot_or_algorithm_state_in_schema():
    layout = generate_layout(10, SamplingOverrides(archetype=Archetype.GRID))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    text = json.dumps(data).lower()
    for forbidden in ("cbba_bid", "karma_score", "robot_position", "task_state", "d_star_cost"):
        assert forbidden not in text
