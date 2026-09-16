"""Node/edge attribute vocabulary for the navigation graph (Section M).

These are plain dict-attribute keys stored on ``networkx`` nodes/edges
(not a separate class hierarchy) so ``networkx.node_link_data`` can
serialize them directly without a custom encoder. This module exists so
every producer/consumer of the graph (builder, metrics, validation,
serialization, visualization) uses the same key names.
"""
from __future__ import annotations

# Node attribute keys
NODE_TYPE = "node_type"           # config.enums.NodeType value
NODE_X = "x"
NODE_Y = "y"
NODE_DEAD_END = "dead_end"        # bool
NODE_ZONE_TYPE = "zone_type"      # str | None
NODE_DOCK_IDS = "dock_ids"        # list[str]

# Edge attribute keys
EDGE_LENGTH_M = "length_m"
EDGE_WIDTH_M = "width_m"
EDGE_WIDTH_CLASS = "width_class"
EDGE_ONE_WAY = "one_way"
EDGE_DIRECTION = "direction"      # "forward" | "backward" | None (two-way)
EDGE_ARCHETYPE_ROLE = "archetype_role"
EDGE_TRAFFIC_WEIGHT = "traffic_weight"
EDGE_SOURCE_IDS = "source_object_ids"
EDGE_TRAVERSABLE = "traversable"
