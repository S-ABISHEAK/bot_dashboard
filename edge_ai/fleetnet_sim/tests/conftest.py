import json

import pytest
from fleetnet_layout.config.enums import Archetype, ScaleClass
from fleetnet_layout.generation.generator import generate_layout
from fleetnet_layout.generation.sampling import SamplingOverrides
from fleetnet_layout.serialization.json_io import to_json_dict

from fleetnet_sim.integration.world_bridge import build_world_bridge

# All DB-backed tests write here, never at the real `fleetnet_sim`
# database `simulate`/`batch`/etc. use for actual work. Every test file
# used to hardcode the real DSN directly, which meant every pytest run
# left permanent junk rows behind (310 accumulated across this project's
# own development before this was caught and fixed) — a real database
# meant to hold genuine experiment data was being silently polluted by
# the test suite. Centralizing it here means one place to change, and
# `_ensure_test_db_exists` below means a fresh checkout doesn't need a
# manual `CREATE DATABASE` step.
TEST_DSN = "postgresql://fleetnet:fleetnet@localhost:5432/fleetnet_sim_test"
_ADMIN_DSN = "postgresql://fleetnet:fleetnet@localhost:5432/postgres"


def _ensure_test_db_exists() -> None:
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(_ADMIN_DSN, future=True)
        with engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'fleetnet_sim_test'")).scalar_one_or_none()
            if not exists:
                conn.execute(text("CREATE DATABASE fleetnet_sim_test OWNER fleetnet"))
    except Exception:
        pass  # DB unreachable entirely -- the usual _db_available() skip-mark handles this


def db_available(dsn: str = TEST_DSN) -> bool:
    from sqlalchemy import text

    from fleetnet_sim.storage.db import make_session_factory

    try:
        _ensure_test_db_exists()
        s = make_session_factory(dsn)()
        s.execute(text("SELECT 1"))
        s.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def small_layout_dict():
    layout = generate_layout(1, SamplingOverrides(archetype=Archetype.GRID, scale_class=ScaleClass.SMALL))
    data = to_json_dict(layout.config, layout.result, layout.graph, layout.metrics, layout.validation)
    # round-trip through JSON to catch anything that only survives in-memory
    return json.loads(json.dumps(data))


@pytest.fixture(scope="session")
def small_bridge(small_layout_dict):
    return build_world_bridge(small_layout_dict)
