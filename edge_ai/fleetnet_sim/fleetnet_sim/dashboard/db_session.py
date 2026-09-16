"""Shared DB-session context manager for dashboard routes.

Every route used to create a session via
``request.app.state.session_factory()`` directly and never close it. A
SQLAlchemy ``Session`` checks out a pooled connection on first use and
holds it until ``.close()`` is called (relying on garbage collection is
unreliable, especially under reference cycles) -- so every un-closed
request permanently leaked one pooled connection. The Watch tab's
``/frames`` endpoint is polled on an interval, so it was the first to
exhaust the pool (default QueuePool: size 5 + overflow 10 = 15) and
raise ``sqlalchemy.exc.TimeoutError``. Route handlers must use this
context manager instead of calling the factory directly.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy.orm import Session


@contextmanager
def db_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
