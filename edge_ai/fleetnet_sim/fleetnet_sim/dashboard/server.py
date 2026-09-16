"""Starts the dashboard's local FastAPI server. Called by the
``dashboard`` CLI subcommand (`fleetnet_sim/cli/main.py::cmd_dashboard`).
"""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.storage.db import init_schema


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    dsn: str = "postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim",
    layouts_dirs: list[str] | None = None,
    open_browser: bool = True,
) -> None:
    # Idempotent -- same call _run_simulation makes -- so the dashboard
    # works on a completely fresh database with zero manual setup.
    init_schema(dsn)

    app = create_app(dsn, layouts_dirs)
    url = f"http://{host}:{port}"
    print(f"FleetNet dashboard running at {url}  (Ctrl+C to stop)")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
