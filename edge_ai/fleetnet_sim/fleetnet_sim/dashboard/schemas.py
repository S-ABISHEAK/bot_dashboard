"""Pydantic request/response models for the dashboard API — same schema
library already used throughout the rest of the project
(`config/schema.py`), just applied to HTTP payloads instead of
simulation config.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class LaunchRequest(BaseModel):
    layout_id: Optional[str] = None
    layout_path: Optional[str] = None
    preset: Optional[str] = None
    robots: Optional[int] = None
    dt: Optional[float] = None
    duration_s: Optional[float] = None
    arrival_rate: Optional[float] = None
    seed: int = 0


class LaunchResponse(BaseModel):
    run_id: str
    experiment_id: str
    status: str


class JobStatusResponse(BaseModel):
    run_id: str
    status: str
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str


class GenerateLayoutRequest(BaseModel):
    archetype: Optional[str] = None
    scale_class: Optional[str] = None
    industry_type: Optional[str] = None
    dock_wall: Optional[str] = None
    irregularity_level: Optional[float] = None
    seed: Optional[int] = None


class GenerateLayoutResponse(BaseModel):
    job_id: str
    status: str


class GenerateStatusResponse(BaseModel):
    job_id: str
    status: str
    layout_id: Optional[str] = None
    resolved: dict = {}
    error: Optional[dict] = None


class ExportDatasetRequest(BaseModel):
    run_ids: list[str]


class ExportDatasetResponse(BaseModel):
    job_id: str
    status: str


class ExportDatasetStatusResponse(BaseModel):
    job_id: str
    status: str
    results: dict = {}
    errors: dict = {}
