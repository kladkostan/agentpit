import sqlite3
from unittest.mock import patch

import pytest

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework
from agentpit.polymarket.polymarket_sync import (
    POLYMARKET_GAMMA_URL,
    _is_market_expired,
    _polymarket_to_erc1155_tokens,
    fetch_all_polymarket_markets,
    fetch_polymarket_market,
    fetch_and_sync_polymarket_markets,
)



@pytest.fixture()
def db():
    """In-memory SQLite database with all tables created."""
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    yield conn
    conn.close()


def test_sync_polymarket_markets_syncs_real_markets_to_db(db):
    """Test syncing live Polymarket markets into a local DB.

    Hits the real Polymarket API and mirrors each market onto the local
    CTF + Exchange — so anvil and the deployed exchange must be up.
    """
    from agentpit.config import Settings
    from agentpit.onchain.admin import OnchainAdmin
    from agentpit.onchain.contracts import Contracts
    from agentpit.onchain.deployment import Deployment
    from agentpit.onchain.web3_client import Web3Client

    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)
    admin = OnchainAdmin(client, Contracts(client.web3, deployment))

    created_markets = fetch_and_sync_polymarket_markets(db, admin)

    # We expect many markets to be created, but the exact number varies.
    assert len(created_markets) > 5

    db_markets, total = TableRead.list_markets(db, limit=len(created_markets) + 1)
    assert total == len(created_markets)
    assert len(db_markets) == len(created_markets)

    first_synced = created_markets[0]
    first_db = db_markets[0]

    assert first_db.market_id == first_synced.market_id
    assert first_db.question == first_synced.question
    assert first_db.description == first_synced.description
    assert len(first_db.erc1155_tokens) > 0

    # Idempotent: a second sync against the same upstream set adds nothing.
    created_markets = fetch_and_sync_polymarket_markets(db, admin)

    assert created_markets == []
