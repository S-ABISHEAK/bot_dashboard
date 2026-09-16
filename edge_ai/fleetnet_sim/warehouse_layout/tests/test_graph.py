import networkx as nx

from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides


def test_graph_connected_for_valid_layout():
    layout = generate_layout(1, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    assert layout.validation.valid
    assert nx.number_connected_components(layout.graph) == 1


def test_bottleneck_candidates_are_derived_not_authored():
    layout = generate_layout(4, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.MEDIUM))
    for aisle in layout.result.all_aisles:
        assert "bottleneck" not in aisle.metadata
    assert isinstance(layout.metrics.bottleneck_candidates, list)


def test_dead_end_nodes_flagged():
    layout = generate_layout(5, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    g = layout.graph
    for node, attrs in g.nodes(data=True):
        if attrs.get("zone_type") is not None:
            continue
        if g.degree(node) == 1:
            assert attrs["dead_end"] is True
        else:
            assert attrs["dead_end"] is False
