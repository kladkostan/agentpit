import os

# Tests run against a real local Postgres (the suite already requires anvil +
# the deployed exchange — no off-mode). Each test gets a clean DB via TRUNCATE
# and its own DbSession pool, overridden onto the shared app.
os.environ.setdefault("AGENTPIT_DATABASE_URL", "postgresql:///agentpit_test")
os.environ.setdefault("AGENTPIT_POOL_MIN_SIZE", "0")  # leaked create_app pools hold 0 conns
os.environ.setdefault("AGENTPIT_POOL_MAX_IDLE", "5")  # shed idle connections fast in tests
os.environ.setdefault("SYNC", "false")
# The liquidity engine provisions the single mirror house account at startup; never
# let a developer's .env (LIQUIDITY_ENGINE=true) leak in and do that per test.
os.environ.setdefault("LIQUIDITY_ENGINE", "false")
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import psycopg
import pytest

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate
from tests.db_helpers import TEST_DSN, fresh_test_db

# Ensure the schema exists once up-front (before the first truncate).
_boot = psycopg.connect(TEST_DSN, autocommit=True)
TableCreate.create_all_tables(_boot)
_boot.close()


def _truncate_all() -> None:
    with psycopg.connect(TEST_DSN, autocommit=True) as c:
        tables = [
            r[0]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            ).fetchall()
        ]
        if tables:
            c.execute(
                "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
            )


@pytest.fixture(autouse=True)
def _isolated_db_session():
    """Clean the shared test DB and give each test its own DbSession pool,
    overridden onto the singleton app (the app's lifespan closes its own
    db_session on TestClient shutdown, so endpoints must use the override)."""
    _truncate_all()
    # The /events listing has a per-process TTL cache; clear it so a previous
    # test's cached page can't leak into one that hits the same (limit, offset).
    from agentpit.api.routes import events as _events_route

    _events_route._events_cache.clear()
    before = {id(s) for s in DbSession._open}
    fresh = fresh_test_db()
    previous = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = lambda: fresh
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db_session, None)
        else:
            app.dependency_overrides[get_db_session] = previous
        # Close every session created during this test (fresh + any pools
        # leaked by per-test create_app()); keep the import-time singleton.
        for s in list(DbSession._open):
            if id(s) not in before:
                s.close()
