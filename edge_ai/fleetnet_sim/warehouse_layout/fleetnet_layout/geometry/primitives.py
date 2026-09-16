"""Typed geometry primitives layered over Shapely.

Every generated physical object (rack block, aisle, zone, dock, column,
exclusion) carries a stable string ``id`` and a Shapely polygon. Keeping
these together in one small dataclass (rather than passing bare Shapely
geometries around) is what lets ``serialization.json_io`` losslessly
round-trip geometry + identity, and what future telemetry (Section AI)
will reference by id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle, meters, world frame. (x, y) is the min corner."""

    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

    def to_polygon(self) -> Polygon:
        return box(self.x, self.y, self.x2, self.y2)

    def to_points(self) -> list[tuple[float, float]]:
        return [(self.x, self.y), (self.x2, self.y), (self.x2, self.y2), (self.x, self.y2)]


@dataclass
class GeoObject:
    """A named, typed physical object with a stable id and polygon geometry,
    plus a free-form metadata dict for archetype-role/traffic-weight/etc."""

    id: str
    kind: str
    polygon: Polygon
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def points(self) -> list[tuple[float, float]]:
        return list(self.polygon.exterior.coords)[:-1]

    @property
    def area_m2(self) -> float:
        return float(self.polygon.area)

    @property
    def centroid(self) -> tuple[float, float]:
        c = self.polygon.centroid
        return (float(c.x), float(c.y))


def polygon_from_points(points: list[tuple[float, float]]) -> Polygon:
    return Polygon(points)
