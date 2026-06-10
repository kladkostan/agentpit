# tests/onchain/test_liquidity_lifespan.py
import asyncio

from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.liquidity import feed


def test_mirror_disabled_by_default():
    app = create_app(Settings())
    with TestClient(app):
        pass  # lifespan runs; no mirror tasks, no house provisioning, no crash


def test_mirror_enabled_spawns_and_cancels_cleanly(monkeypatch):
    # Stub the feed: a connection task that idles forever (no network).
    async def fake_connection(state, assets, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(feed, "run_connection", fake_connection)
    monkeypatch.setattr(feed, "fetch_books_rest", lambda ids, **kw: [])

    s = Settings(liquidity_engine_enabled=True, liquidity_house_account_count=1,
                 liquidity_funding_drips=1, mirror_target_refresh_seconds=0.1)
    app = create_app(s)
    with TestClient(app) as client:
        r = client.get("/markets")        # API serves while the mirror idles
        assert r.status_code == 200
    # Clean shutdown (no hang, no unraised CancelledError) is the assertion.
