"""GET /api/layouts, GET /api/layouts/{layout_id} — layout browsing.
Pure filesystem reads, no database involved.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/layouts")
def list_layouts(request: Request):
    index = request.app.state.layout_index
    return {"layouts": index.list_summaries()}


@router.get("/layouts/{layout_id}")
def get_layout(layout_id: str, request: Request):
    index = request.app.state.layout_index
    path = index.find_path(layout_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no such layout_id: {layout_id!r}")
    with open(path) as f:
        return json.load(f)
