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
# The leaderboard timer walks every traded account's chain balance; keep it
# off the same way the other timers above are, so a developer's .env can't
# make every TestClient(app) lifespan start ticking it.
os.environ.setdefault("AGENTPIT_LEADERBOARD_ENABLED", "false")
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import psycopg
import pytest

from agentpit.api.deps import get_db_session, get_workos_client
from agentpit.api.main import app
from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate
from tests.db_helpers import TEST_DSN, fresh_test_db

# Ensure the schema exists once up-front (before the first truncate).
_boot = psycopg.connect(TEST_DSN, autocommit=True)
TableCreate.create_all_tables(_boot)
_boot.close()

# The offline double is the DEFAULT WorkOS client for the shared app, not just
# something individual tests remember to install.
#
# `agentpit.api.main` calls load_dotenv() at import, and this repo's .env
# carries a live WORKOS_API_KEY, so the app factory wires a RealWorkOsClient
# pointed at https://api.workos.com. A test that posts /auth/code and forgets
# its double would then hit the real API with the production key -- and
# measured 2026-08-11, POST /user_management/magic_auth CREATES the WorkOS user
# and MAILS the code, so it would send third-party mail and pass, on every CI
# run, with nothing to notice it by. Offline by construction instead of by
# everyone remembering. One shared instance rather than a fresh one per
# request, because the fake holds the issued codes: a per-request instance
# would make a forgotten fixture fail as a confusing 401 instead of working.
_default_workos = FakeWorkOsClient()
app.dependency_overrides[get_workos_client] = lambda: _default_workos


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
    # Same reason as the events cache above: /tags holds a single 30s slot, so
    # a response built from a previous test's rows would be served to the next.
    from agentpit.api.routes import tags as _tags_route

    _tags_route._tags_cache = None
    # Same reason as the events cache above: a cached board from a previous
    # test would be served to the next one, and a test that asserts the
    # endpoint makes no chain call proves nothing if it never recomputes.
    from agentpit.api.routes import leaderboard as _leaderboard_route

    _leaderboard_route._board_cache.clear()
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
