import os

# Force tests to use an in-memory DB, disable Polymarket sync, and skip the
# on-chain bring-up so the test suite can run without anvil. Set BEFORE any
# agentpit module is imported so Settings() picks these up.
os.environ.setdefault("AGENTPIT_DB_PATH", ":memory:")
os.environ.setdefault("SYNC", "false")
os.environ.setdefault("AGENTPIT_ONCHAIN_DISABLED", "true")
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import pytest

from agentpit.api.deps import get_db_session
from agentpit.db.session import DbSession
from agentpit.api.main import app


@pytest.fixture(autouse=True)
def _isolated_db_session():
    """Give each test a fresh in-memory DB on the shared main.app."""
    fresh = DbSession(":memory:")
    previous = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = lambda: fresh
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db_session, None)
        else:
            app.dependency_overrides[get_db_session] = previous
        fresh.close()
