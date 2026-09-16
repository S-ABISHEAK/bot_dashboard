"""POST /api/layouts/generate, GET /api/layouts/generate/{job_id}/status
-- generating brand new warehouse layouts from the dashboard, instead of
only browsing ones that already exist on disk.

Runs `warehouse_layout`'s real `generate_layout()` (no reimplementation)
in a background thread via `LayoutGenJobRegistry` -- generation is not
cheap enough to run inline in a request handler (see that module's
docstring). The dock_wall field intentionally only accepts south/north:
the sampler itself never auto-picks east/west, and forcing them via an
override risks broken geometry on archetypes that don't rotate the
footprint (see `reserve_zone_band`'s docstring in warehouse_layout).
"""
from __future__ import annotations

import random
import uuid

from fastapi import APIRouter, HTTPException, Request

from fleetnet_layout.config.enums import Archetype, DockWall, IndustryType, ScaleClass
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_sim.dashboard.layout_jobs import ConcurrencyLimitError
from fleetnet_sim.dashboard.schemas import GenerateLayoutRequest, GenerateLayoutResponse, GenerateStatusResponse

router = APIRouter()

_ALLOWED_DOCK_WALLS = {"south", "north"}


def _enum_or_422(enum_cls, value: str | None, field_name: str):
    if value is None or value == "":
        return None
    try:
        return enum_cls(value)
    except ValueError:
        valid = ", ".join(e.value for e in enum_cls)
        raise HTTPException(status_code=422, detail=f"invalid {field_name}: {value!r} (valid: {valid})")


@router.post("/layouts/generate", response_model=GenerateLayoutResponse, status_code=202)
def generate_layout_route(body: GenerateLayoutRequest, request: Request):
    if body.dock_wall and body.dock_wall not in _ALLOWED_DOCK_WALLS:
        raise HTTPException(status_code=422, detail=f"dock_wall must be one of {sorted(_ALLOWED_DOCK_WALLS)} or omitted (random)")

    overrides = SamplingOverrides(
        archetype=_enum_or_422(Archetype, body.archetype, "archetype"),
        scale_class=_enum_or_422(ScaleClass, body.scale_class, "scale_class"),
        industry_type=_enum_or_422(IndustryType, body.industry_type, "industry_type"),
        dock_wall=_enum_or_422(DockWall, body.dock_wall, "dock_wall"),
        irregularity_level=body.irregularity_level,
    )
    seed = body.seed if body.seed is not None else random.randint(0, 2**31 - 1)
    job_id = f"gen_{uuid.uuid4().hex[:10]}"

    try:
        request.app.state.layout_gen_jobs.start(job_id, seed, overrides)
    except ConcurrencyLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    return GenerateLayoutResponse(job_id=job_id, status="started")


@router.get("/layouts/generate/{job_id}/status", response_model=GenerateStatusResponse)
def generate_layout_status(job_id: str, request: Request):
    job = request.app.state.layout_gen_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no tracked job for job_id: {job_id!r}")
    return GenerateStatusResponse(
        job_id=job.job_id, status=job.status, layout_id=job.layout_id, resolved=job.resolved, error=job.error
    )
