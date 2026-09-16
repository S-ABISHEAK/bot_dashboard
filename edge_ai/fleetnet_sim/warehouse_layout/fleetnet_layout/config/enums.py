"""Categorical parameter vocabularies shared across the config schema.

Every enum here corresponds to a categorical field in the Section J
parameter schema from the FleetNet warehouse-layout research spec.
"""
from __future__ import annotations

from enum import Enum


class ScaleClass(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


class IndustryType(str, Enum):
    ECOMMERCE = "ecommerce"
    RETAIL = "retail"
    GROCERY = "grocery"
    MANUFACTURING = "manufacturing"
    AUTOMOTIVE = "automotive"
    ELECTRONICS = "electronics"
    COLD_STORAGE = "cold_storage"
    PHARMA = "pharma"
    PARCEL = "parcel"
    GENERAL_3PL = "general_3pl"


class Archetype(str, Enum):
    FLOW_THROUGH = "flow_through"
    U_FLOW = "u_flow"
    L_FLOW = "l_flow"
    GRID = "grid"
    ZONE_BASED = "zone_based"
    CENTRAL_CORRIDOR = "central_corridor"
    FISHBONE = "fishbone"


class RackType(str, Enum):
    SELECTIVE = "selective"
    DRIVE_IN = "drive_in"
    PUSH_BACK = "push_back"
    CANTILEVER = "cantilever"
    SHELVING = "shelving"
    BULK_FLOOR = "bulk_floor"
    HIGH_DENSITY = "high_density"
    ASRS = "asrs"


class RackOrientation(str, Enum):
    PARALLEL_TO_DOCK = "parallel_to_dock"
    PERPENDICULAR_TO_DOCK = "perpendicular_to_dock"


class AisleWidthClass(str, Enum):
    NARROW_VNA = "narrow_vna"
    NARROW = "narrow"
    STANDARD = "standard"
    WIDE = "wide"


class DockWall(str, Enum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class ZoneType(str, Enum):
    RECEIVING = "receiving"
    SHIPPING = "shipping"
    STAGING = "staging"
    PICKING = "picking"
    PACKING = "packing"
    RETURNS = "returns"
    CHARGING = "charging"
    OFFICE = "office"


class ArchetypeRole(str, Enum):
    """Edge/aisle role tag used in the navigation graph (Section M)."""

    MAIN = "main"
    SECONDARY = "secondary"
    CROSS = "cross"
    SPINE = "spine"
    FEEDER = "feeder"
    DOCK_APRON = "dock_apron"
    ZONE_ACCESS = "zone_access"


class NodeType(str, Enum):
    INTERSECTION = "intersection"
    DEAD_END = "dead_end"
    ZONE_ENTRY = "zone_entry"
    DOCK_ENTRY = "dock_entry"
    WAYPOINT = "waypoint"
