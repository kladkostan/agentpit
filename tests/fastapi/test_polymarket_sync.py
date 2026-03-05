import sqlite3

import pytest

from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.polymarket.polymarket_sync import (
    _polymarket_to_erc1155_tokens,
    fetch_all_polymarket_markets,
    fetch_polymarket_market,
    sync_polymarket_markets,
)


@pytest.fixture()
def db():
    """In-memory SQLite database with all tables created."""
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# _polymarket_to_erc1155_tokens
# ---------------------------------------------------------------------------


class TestPolymarketToErc1155Tokens:
    def test_basic_conversion(self):
        pm_market = {
            "tokens": [
                {"token_id": "111", "outcome": "Yes"},
                {"token_id": "222", "outcome": "No"},
            ]
        }
        assert _polymarket_to_erc1155_tokens(pm_market) == [
            ("111", "Yes"),
            ("222", "No"),
        ]

    def test_empty_tokens(self):
        assert _polymarket_to_erc1155_tokens({"tokens": []}) == []

    def test_missing_tokens_key(self):
        assert _polymarket_to_erc1155_tokens({}) == []

    def test_multiple_outcomes(self):
        pm_market = {
            "tokens": [
                {"token_id": "1", "outcome": "A"},
                {"token_id": "2", "outcome": "B"},
                {"token_id": "3", "outcome": "C"},
            ]
        }
        result = _polymarket_to_erc1155_tokens(pm_market)
        assert len(result) == 3
        assert result[2] == ("3", "C")


# ---------------------------------------------------------------------------
# fetch_polymarket_market (Integration Test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFetchPolymarketMarket:
    def test_fetches_real_market_by_id(self):
        """Test fetching a known, valid market from the live Polymarket API."""
        # This is a known market: "Will the Fed cut rates by the end of the July 2024 meeting?"
        condition_id = "0x45554489f6a1f17e0e8233552f40cb1e3a66955c9d9f1810a5c14e5b0699115b"
        market = fetch_polymarket_market(condition_id)

        assert market is not None
        assert market["condition_id"] == condition_id
        assert "Will the Fed cut rates" in market["question"]
        assert "tokens" in market and len(market["tokens"]) > 0

    def test_returns_none_for_nonexistent_market(self):
        """Test fetching a non-existent market returns None."""
        condition_id = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        market = fetch_polymarket_market(condition_id)
        assert market is None

    def test_returns_none_for_invalid_id(self):
        """Test fetching with a badly formatted ID returns None."""
        market = fetch_polymarket_market("not-a-valid-id")
        assert market is None


# ---------------------------------------------------------------------------
# fetch_all_polymarket_markets (Integration Test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFetchAllPolymarketMarkets:
    def test_fetches_real_markets(self):
        """Test that we can fetch markets from the live Polymarket API."""
        markets = fetch_all_polymarket_markets()
        assert isinstance(markets, list)
        # There should be a significant number of markets
        assert len(markets) > 100

        # Check the structure of a sample market
        market = markets[0]
        assert "question" in market
        assert "condition_id" in market
        assert "tokens" in market
        assert isinstance(market["tokens"], list)


# ---------------------------------------------------------------------------
# sync_polymarket_markets (Integration Test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSyncPolymarketMarkets:
    def test_syncs_real_markets_to_db(self, db):
        """Test syncing live Polymarket markets into a local DB."""
        # This will hit the actual Polymarket API
        created_markets = sync_polymarket_markets(db)

        # We expect many markets to be created, but the exact number varies.
        # Let's check that a reasonable number were created.
        assert len(created_markets) > 100

        # Verify they exist in the database
        db_markets, total = TableRead.list_markets(db, limit=len(created_markets) + 1)
        assert total == len(created_markets)
        assert len(db_markets) == len(created_markets)

        # Check a sample market that was created
        first_synced = created_markets[0]
        first_db = db_markets[0]

        assert first_db.market_id == first_synced.market_id
        assert first_db.question == first_synced.question
        assert first_db.description == first_synced.description
        assert first_db.market_state == "DRAFT"
        assert len(first_db.erc1155_tokens) > 0
