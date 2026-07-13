# tests/onchain/test_liquidity_lifespan.py
import asyncio

from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.liquidity import feed

from tests.onchain._helpers import ADMIN_HDR


def test_mirror_disabled_by_default():
    app = create_app(Settings())
    with TestClient(app):
        pass  # lifespan runs; no mirror tasks, no house provisioning, no crash


def test_mirror_enabled_spawns_and_cancels_cleanly(monkeypatch):
    import time
    import uuid

    calls = []

    async def fake_connection(state, assets, **kw):
        calls.append(list(assets))
        await asyncio.Event().wait()

    monkeypatch.setattr(feed, "run_connection", fake_connection)
    monkeypatch.setattr(feed, "fetch_books_rest", lambda ids, **kw: [])

    s = Settings(liquidity_engine_enabled=True, liquidity_house_account_count=1,
                 liquidity_funding_drips=1, mirror_target_refresh_seconds=0.1)
    app = create_app(s)
    with TestClient(app) as client:
        r = client.get("/markets")        # API serves while the mirror idles
        assert r.status_code == 200
        # Give the engine a synced market; the 0.1s target refresh must pick it
        # up and spawn a (stubbed) feed connection for its Polymarket asset.
        m = client.post("/markets", json={
            "question": f"LS {uuid.uuid4().hex[:6]}?", "description": "x",
            "outcome_labels": ["YES", "NO"]}, headers=ADMIN_HDR).json()
        from agentpit.db.session import DbSession
        db = DbSession(s.database_url)
        with db.write() as conn:
            conn.execute(
                "UPDATE markets SET MARKET_STATE='ACTIVE', "
                "POLYMARKET_CONDITION_ID=%s, POLYMARKET_YES_TOKEN_ID=%s "
                "WHERE CONDITION_ID=%s",
                ("0xpm-ls", "PM-LS", m["condition_id"]["value"]))
        deadline = time.time() + 5.0
        while time.time() < deadline and not calls:
            time.sleep(0.05)
        assert calls and calls[0] == ["PM-LS"], \
            "target refresh must spawn a feed connection for the synced market"
    # Clean shutdown (no hang, no unraised CancelledError) is the assertion.
