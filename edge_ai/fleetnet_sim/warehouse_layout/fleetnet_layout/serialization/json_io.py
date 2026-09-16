"""Canonical JSON serialization (Section Z).

``layout_id`` is derived deterministically from seed + the full sampled
config (a stable hash), never a random UUID — this is what makes
"re-run the same seed -> byte-identical output" hold for the id field
too, not just the geometry (see the plan's Determinism design decision).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import networkx as nx

from fleetnet_layout import GENERATOR_VERSION, SCHEMA_VERSION
from fleetnet_layout.config.schema import LayoutConfig
from fleetnet_layout.generation.types import LayoutBuildResult
from fleetnet_layout.graph.metrics import DerivedMetrics
from fleetnet_layout.validation.validator import ValidationResult


def _geo_object_to_dict(obj) -> dict[str, Any]:
    return {
        "id": obj.id,
        "kind": obj.kind,
        "points": [list(p) for p in obj.points],
        "metadata": obj.metadata,
    }


def compute_layout_id(cfg: LayoutConfig) -> str:
    payload = cfg.model_dump_json().encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"wh_{cfg.warehouse.seed}_{digest}"


def to_json_dict(
    cfg: LayoutConfig,
    result: LayoutBuildResult,
    graph: nx.Graph,
    metrics: DerivedMetrics,
    validation: ValidationResult,
) -> dict[str, Any]:
    footprint_pts = result.footprint.to_points()

    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "layout_id": compute_layout_id(cfg),
        "seed": cfg.warehouse.seed,
        "parameters": json.loads(cfg.model_dump_json()),
        "warehouse": {
            "length_m": cfg.warehouse.length_m,
            "width_m": cfg.warehouse.width_m,
            "area_m2": cfg.warehouse.area_m2,
            "clear_height_m": cfg.warehouse.clear_height_m,
            "scale_class": cfg.warehouse.scale_class.value,
            "industry_type": cfg.warehouse.industry_type.value,
            "archetype": cfg.warehouse.archetype.value,
            "aspect_ratio": cfg.warehouse.aspect_ratio,
        },
        "geometry": {
            "footprint": [list(p) for p in footprint_pts],
            "racks": [_geo_object_to_dict(o) for o in result.racks],
            "aisles": [_geo_object_to_dict(o) for o in result.all_aisles],
            "zones": [_geo_object_to_dict(o) for o in result.zones],
            "columns": [_geo_object_to_dict(o) for o in result.columns],
            "exclusions": [_geo_object_to_dict(o) for o in result.exclusions],
            "docks": [_geo_object_to_dict(o) for o in result.docks],
            "fire_lanes": list(result.fire_lane_ids),
        },
        "navigation_graph": nx.node_link_data(graph, edges="links"),
        "derived_metrics": {
            "aisle_count": metrics.aisle_count,
            "intersection_count": metrics.intersection_count,
            "dead_end_count": metrics.dead_end_count,
            "storage_density": metrics.storage_density,
            "bottleneck_candidates": metrics.bottleneck_candidates,
            "graph_diameter": metrics.graph_diameter,
            "average_path_length": metrics.average_path_length,
            "connected_components": metrics.connected_components,
            "aspect_ratio": metrics.aspect_ratio,
        },
        "validation": {
            "valid": validation.valid,
            "failures": validation.failures,
            "warnings": validation.warnings,
        },
    }


def write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def read_json(path: str) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def graph_from_json(data: dict[str, Any]) -> nx.Graph:
    return nx.node_link_graph(data["navigation_graph"], edges="links")


def _geo_object_from_dict(d: dict[str, Any]):
    from fleetnet_layout.geometry.primitives import GeoObject, polygon_from_points

    return GeoObject(id=d["id"], kind=d["kind"], polygon=polygon_from_points(d["points"]), metadata=d["metadata"])


def layout_from_json_dict(data: dict[str, Any]):
    """Reconstruct a renderable, read-only layout from stored JSON — used
    by the CLI's ``render`` command so a saved layout can be re-rendered
    without regenerating it. Only carries what ``visualization.renderer``
    needs (config, geometry, graph, bottleneck list), not a full
    ``GeneratedLayout`` (there's no ``ValidationResult``/attempts to
    reconstruct meaningfully from a static file)."""
    from types import SimpleNamespace

    from fleetnet_layout.generation.types import LayoutBuildResult
    from fleetnet_layout.geometry.primitives import Rect

    cfg = LayoutConfig(**data["parameters"])
    geo = data["geometry"]

    footprint_pts = geo["footprint"]
    xs = [p[0] for p in footprint_pts]
    ys = [p[1] for p in footprint_pts]
    footprint = Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    all_aisles = [_geo_object_from_dict(d) for d in geo["aisles"]]
    result = LayoutBuildResult(
        footprint=footprint,
        racks=[_geo_object_from_dict(d) for d in geo["racks"]],
        main_aisles=[a for a in all_aisles if a.metadata.get("archetype_role") in ("main", "spine")],
        secondary_aisles=[a for a in all_aisles if a.metadata.get("archetype_role") in ("secondary", "feeder")],
        cross_aisles=[a for a in all_aisles if a.metadata.get("archetype_role") == "cross"],
        zones=[_geo_object_from_dict(d) for d in geo["zones"]],
        docks=[_geo_object_from_dict(d) for d in geo["docks"]],
        columns=[_geo_object_from_dict(d) for d in geo["columns"]],
        exclusions=[_geo_object_from_dict(d) for d in geo["exclusions"]],
        fire_lane_ids=geo["fire_lanes"],
    )
    graph = graph_from_json(data)
    metrics = SimpleNamespace(bottleneck_candidates=data["derived_metrics"]["bottleneck_candidates"])

    return SimpleNamespace(config=cfg, result=result, graph=graph, metrics=metrics)
