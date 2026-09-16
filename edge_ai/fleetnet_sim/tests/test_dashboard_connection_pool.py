"""Regression guard for the dashboard's DB-connection leak: every route
used to call ``request.app.state.session_factory()`` directly and never
close the resulting Session, so each request permanently held a pooled
connection checked out. The Watch tab's ``/frames`` endpoint is polled
on an interval, so a real Watch session reliably hit
``sqlalchemy.exc.TimeoutError: QueuePool limit ... reached`` after
about 15 polls (default pool: size 5 + overflow 10). Fixed by routing
every route through ``dashboard.db_session.db_session``, which closes
the session in a ``finally`` block. This test fires more requests than
the pool can hold, across both success and 404 (error) response paths,
and asserts none of them time out waiting for a connection.
"""
from __future__ import annotations

import gc
from contextlib import contextmanager

import pytest
from conftest import TEST_DSN as DSN
from conftest import db_available as _db_available
from fastapi.testclient import TestClient

from fleetnet_sim.dashboard.app import create_app
from fleetnet_sim.storage.db import init_schema


@contextmanager
def _gc_disabled():
    """Un-closed sessions in the old buggy code only got released back
    to the pool when CPython's cyclic GC happened to run (Session has
    internal reference cycles a plain refcount drop can't collect) --
    so this test failed or passed depending on unrelated GC timing.
    Disabling gc for the duration makes the leak (and the fix)
    deterministic: without an explicit .close() in a finally block, the
    N_REQUESTS loop below reliably exhausts the pool at request 16."""
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()

pytestmark = pytest.mark.skipif(not _db_available(), reason="TimescaleDB not reachable at localhost:5432 (docker compose up -d)")

# Default QueuePool is size=5, max_overflow=10 -> 15 concurrent checkouts
# before a 16th request would block/timeout if none are ever released.
N_REQUESTS = 30


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    init_schema(DSN)
    layouts_dir = tmp_path_factory.mktemp("pool_test_layouts")
    app = create_app(DSN, layouts_dirs=[str(layouts_dir)])
    return TestClient(app)


def test_repeated_list_runs_does_not_exhaust_the_pool(client):
    with _gc_disabled():
        for _ in range(N_REQUESTS):
            resp = client.get("/api/runs")
            assert resp.status_code == 200


def test_repeated_404_lookups_do_not_exhaust_the_pool(client):
    # The error path used to leak just as badly as the success path --
    # there was no try/finally at all, so a 404 (raised mid-handler)
    # never closed its session either.
    with _gc_disabled():
        for _ in range(N_REQUESTS):
            resp = client.get("/api/runs/not_a_real_run_id")
            assert resp.status_code == 404


def test_repeated_frames_lookups_do_not_exhaust_the_pool(client):
    # The exact endpoint from the reported traceback.
    with _gc_disabled():
        for _ in range(N_REQUESTS):
            resp = client.get("/api/runs/not_a_real_run_id/frames")
            assert resp.status_code == 404
