"""FastAPI application factory for the FleetNet dashboard."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fleetnet_sim.dashboard import routes_datasets, routes_generate, routes_layouts, routes_report, routes_runs, routes_simulate
from fleetnet_sim.dashboard.dataset_jobs import DatasetExportJobRegistry
from fleetnet_sim.dashboard.jobs import JobRegistry
from fleetnet_sim.dashboard.layout_index import DEFAULT_LAYOUT_DIRS, LayoutIndex
from fleetnet_sim.dashboard.layout_jobs import LayoutGenJobRegistry
from fleetnet_sim.storage.db import make_session_factory

STATIC_DIR = Path(__file__).parent / "static"


def create_app(dsn: str, layouts_dirs: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="FleetNet Dashboard")
    app.state.dsn = dsn
    app.state.session_factory = make_session_factory(dsn)
    app.state.jobs = JobRegistry()
    app.state.dataset_jobs = DatasetExportJobRegistry()
    resolved_layout_dirs = layouts_dirs or DEFAULT_LAYOUT_DIRS
    app.state.layout_index = LayoutIndex(resolved_layout_dirs)
    # New layouts are written into the first configured layout directory
    # -- the same one the index already scans, so a freshly generated
    # layout shows up via GET /api/layouts on the very next request with
    # no extra wiring.
    app.state.layout_gen_jobs = LayoutGenJobRegistry(Path(resolved_layout_dirs[0]))

    app.include_router(routes_layouts.router, prefix="/api")
    app.include_router(routes_runs.router, prefix="/api")
    app.include_router(routes_report.router, prefix="/api")
    app.include_router(routes_generate.router, prefix="/api")
    app.include_router(routes_datasets.router, prefix="/api")
    app.include_router(routes_simulate.router, prefix="/api")

    # html=True serves static/index.html for "/" and any unmatched path,
    # so the single-page app's client-side routing (tab switching) works
    # without a dedicated catch-all route.
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app
