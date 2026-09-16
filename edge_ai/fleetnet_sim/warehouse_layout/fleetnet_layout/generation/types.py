"""Shared intermediate representation produced by every archetype builder,
consumed by graph/builder.py, validation/*, and serialization/json_io.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fleetnet_layout.geometry.primitives import GeoObject, Rect


@dataclass
class LayoutBuildResult:
    footprint: Rect
    racks: list[GeoObject] = field(default_factory=list)
    main_aisles: list[GeoObject] = field(default_factory=list)
    secondary_aisles: list[GeoObject] = field(default_factory=list)
    cross_aisles: list[GeoObject] = field(default_factory=list)
    zones: list[GeoObject] = field(default_factory=list)
    docks: list[GeoObject] = field(default_factory=list)
    columns: list[GeoObject] = field(default_factory=list)
    exclusions: list[GeoObject] = field(default_factory=list)
    fire_lane_ids: list[str] = field(default_factory=list)

    @property
    def all_aisles(self) -> list[GeoObject]:
        return self.main_aisles + self.secondary_aisles + self.cross_aisles

    @property
    def all_exclusions(self) -> list[GeoObject]:
        return self.columns + self.exclusions
