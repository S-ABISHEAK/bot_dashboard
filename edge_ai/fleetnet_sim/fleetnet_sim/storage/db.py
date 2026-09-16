"""Engine/session factory + one-time schema + hypertable setup."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from fleetnet_sim.storage.models import Base

_HYPERTABLES = [
    ("robot_state_ts", "ingested_at"),
    ("algorithm_events", "ingested_at"),
    ("route_events", "ingested_at"),
    ("edge_state_ts", "ingested_at"),
    ("node_state_ts", "ingested_at"),
    ("zone_state_ts", "ingested_at"),
    ("conflict_events", "ingested_at"),
    ("congestion_events", "ingested_at"),
    ("communication_events", "ingested_at"),
]


def make_engine(dsn: str, echo: bool = False):
    return create_engine(dsn, echo=echo, future=True)


def make_session_factory(dsn: str, echo: bool = False) -> sessionmaker[Session]:
    engine = make_engine(dsn, echo)
    return sessionmaker(bind=engine, future=True)


def init_schema(dsn: str, echo: bool = False) -> None:
    """Create every table, then promote the three high-frequency tables
    to TimescaleDB hypertables (idempotent — safe to call on every
    ``simulate`` invocation, not just once)."""
    engine = make_engine(dsn, echo)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        for table, time_col in _HYPERTABLES:
            conn.execute(
                text(
                    "SELECT create_hypertable(:table, :time_col, if_not_exists => TRUE, migrate_data => TRUE)"
                ),
                {"table": table, "time_col": time_col},
            )
