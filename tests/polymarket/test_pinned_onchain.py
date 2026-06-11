"""On-chain: a pinned current-window event is created, prepared on the local
CTF, and attached to its series event. Real anvil + deployed contracts.
The Gamma fetch is faked so the test is deterministic (no live Polymarket).
"""

import secrets

import pytest

import agentpit.polymarket.pinned as pinned
from agentpit.config import Settings
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db():
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _admin() -> OnchainAdmin:
    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)
    return OnchainAdmin(client, Contracts(client.web3, deployment))


def _fake_window_event() -> dict:
    nonce = secrets.token_hex(6)
    return {
        "id": "win-1",
        "slug": "btc-updown-5m-1781193600",
        "title": "Bitcoin Up or Down - window",
        "series": [
            {"id": "10684", "slug": "btc-up-or-down-5m", "title": "BTC Up or Down 5m"}
        ],
        "markets": [
            {
                "id": int(secrets.token_hex(4), 16),
                "conditionId": "0x" + secrets.token_hex(32),
                "question": f"Bitcoin Up or Down - {nonce}?",
                "description": "d",
                "slug": "btc-updown-5m-1781193600",
                "active": True,
                "closed": False,
                "startDate": "2026-06-11T16:00:00Z",
                "endDate": "2026-06-11T16:05:00Z",
                "clobTokenIds": '["111","222"]',
                "outcomes": '["Up","Down"]',
            }
        ],
    }


def test_pin_sync_prepares_window_and_groups_under_series(monkeypatch, db):
    admin = _admin()

    # Capture the upstream conditionId from the SAME event the sync consumes,
    # so the "local prepare overrode it" assertion is meaningful.
    event = _fake_window_event()
    upstream_cond = event["markets"][0]["conditionId"]
    monkeypatch.setattr(pinned, "fetch_event_by_slug", lambda slug: event)

    created = pinned.sync_pinned_series(
        db, admin, pinned=[("btc-updown-5m", 300)], now=1781193601
    )

    assert len(created) == 1
    market = created[0]
    # On-chain prepare overrode the upstream conditionId with a locally-derived
    # one; the market is ACTIVE and tradeable.
    assert market.condition_id.value != upstream_cond
    assert market.market_state == MarketState.ACTIVE
    assert len(market.erc1155_tokens) == 2

    market_row = TableRead.read_market(db, market.market_id)
    assert market_row is not None and market_row.event_id is not None

    event_row = TableRead.get_event_by_slug(db, "btc-up-or-down-5m")
    assert event_row is not None
    assert event_row.event_id == market_row.event_id
    assert event_row.polymarket_event_id == "10684"
