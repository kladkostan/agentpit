import sqlite3
from unittest.mock import patch

import pytest

from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead

from agentpit.fastapi.agentpit_server import AgentPitServer
from agentpit.polymarket.polymarket_sync import (
    POLYMARKET_GAMMA_URL,
    _is_market_expired,
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
# _is_market_expired
# ---------------------------------------------------------------------------


class TestIsMarketExpired:
    def test_expired_market(self):
        assert _is_market_expired({"end_date_iso": "2020-01-01T00:00:00Z"}) is True

    def test_future_market(self):
        assert _is_market_expired({"end_date_iso": "2099-12-31T23:59:59Z"}) is False

    def test_missing_end_date(self):
        assert _is_market_expired({}) is False

    def test_empty_end_date(self):
        assert _is_market_expired({"end_date_iso": ""}) is False

    def test_none_end_date(self):
        assert _is_market_expired({"end_date_iso": None}) is False

    def test_invalid_end_date(self):
        assert _is_market_expired({"end_date_iso": "not-a-date"}) is False


# ---------------------------------------------------------------------------
# fetch_all_polymarket_markets (Unit Tests)
# ---------------------------------------------------------------------------


class TestFetchAllPolymarketMarketsUnit:
    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_default_query_params(self, mock_get):
        """Default call should request limit and offset."""
        mock_get.return_value = []
        fetch_all_polymarket_markets()
        url = mock_get.call_args[0][0]
        assert "limit=100" in url
        assert "offset=0" in url

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_include_archived(self, mock_get):
        mock_get.return_value = {"next_cursor": END_CURSOR, "data": []}
        fetch_all_polymarket_markets(archived=True)
        url = mock_get.call_args[0][0]
        assert "archived=true" in url

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_include_closed(self, mock_get):
        mock_get.return_value = {"next_cursor": END_CURSOR, "data": []}
        fetch_all_polymarket_markets(closed=True)
        url = mock_get.call_args[0][0]
        assert "closed=true" in url

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_inactive(self, mock_get):
        mock_get.return_value = {"next_cursor": END_CURSOR, "data": []}
        fetch_all_polymarket_markets(active=False)
        url = mock_get.call_args[0][0]
        assert "active=false" in url

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_filters_expired_markets(self, mock_get):
        """Markets with end_date_iso in the past should be excluded."""
        mock_get.return_value = {
            "next_cursor": END_CURSOR,
            "data": [
                {"question": "Expired", "end_date_iso": "2020-01-01T00:00:00Z"},
                {"question": "Active", "end_date_iso": "2099-12-31T00:00:00Z"},
                {"question": "No date"},
            ],
        }
        result = fetch_all_polymarket_markets()
        questions = [m["question"] for m in result]
        assert "Expired" not in questions
        assert "Active" in questions
        assert "No date" in questions
        assert len(result) == 2

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_pagination(self, mock_get):
        """Test that it loops through pages using offset."""
        # Page 1 (full), Page 2 (partial/empty) to stop
        mock_get.side_effect = [
            [{"question": "M" + str(i)} for i in range(100)],
            [{"question": "Last"}],
        ]
        result = fetch_all_polymarket_markets()
        assert len(result) == 101

        # Check calls
        assert mock_get.call_count == 2

        call1 = mock_get.call_args_list[0][0][0]
        assert "offset=0" in call1

        call2 = mock_get.call_args_list[1][0][0]
        assert "offset=100" in call2

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_pagination_stops_on_empty_list(self, mock_get):
        mock_get.side_effect = [
            [],
        ]
        result = fetch_all_polymarket_markets()
        assert len(result) == 0
        assert mock_get.call_count == 1

    @patch("agentpit.polymarket.polymarket_sync.get")
    def test_raises_on_leaked_archived_markets(self, mock_get):
        """Archived markets leaked by the API should raise an exception."""
        # Gamma API returns a list
        mock_get.return_value = [
            {"question": "Archived", "archived": True},
            {"question": "Not archived", "archived": False},
        ]

        with pytest.raises(ValueError, match="returned archived market"):
            fetch_all_polymarket_markets(archived=False)


# ---------------------------------------------------------------------------
# fetch_polymarket_market (Integration Test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFetchPolymarketMarket:
    def test_fetches_real_market_by_id(self):
        """Test fetching a valid market from the live Polymarket API.

        Since condition_ids can become stale, we first fetch the market list
        to obtain a known-good condition_id, then verify fetch_polymarket_market
        can retrieve it individually.
        """
        markets = fetch_all_polymarket_markets()
        assert len(markets) > 0, "No markets returned from Polymarket API"

        # Pick the first market that has a condition_id and tokens
        sample = next(
            (m for m in markets if m.get("condition_id") and m.get("tokens")),
            None,
        )
        assert sample is not None, "No market with condition_id and tokens found"

        condition_id = sample["condition_id"]
        market = fetch_polymarket_market(condition_id)

        assert market is not None, "fetch_polymarket_market returned None (check network/vpn?)"
        assert market["condition_id"] == condition_id
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
        assert len(markets) > 5

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
        assert len(created_markets) > 5

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


# ---------------------------------------------------------------------------
# sync_polymarket_markets (Unit Test)
# ---------------------------------------------------------------------------


class TestSyncPolymarketMarketsUnit:
    @patch("agentpit.polymarket.polymarket_sync.fetch_all_polymarket_markets")
    def test_updates_existing_polymarket_id(self, mock_fetch_all, db):
        mock_fetch_all.return_value = [
            {
                "question": "Will X happen?",
                "description": "desc",
                "polymarket_id": 42,
                "tokens": [
                    {"token_id": "1", "outcome": "Yes"},
                    {"token_id": "2", "outcome": "No"},
                ],
            },
            {
                "question": "Will X happen duplicate?",
                "description": "desc updated",
                "polymarket_id": 42,
                "tokens": [
                    {"token_id": "3", "outcome": "Yes"},
                    {"token_id": "4", "outcome": "No"},
                ],
            },
        ]

        created = sync_polymarket_markets(db)
        assert len(created) == 1

        markets, total = TableRead.list_markets(db, limit=10)
        assert total == 1
        assert len(markets) == 1
        assert markets[0].polymarket_id == 42
        assert markets[0].question == "Will X happen duplicate?"
        assert markets[0].description == "desc updated"
        assert markets[0].erc1155_tokens == [("3", "Yes"), ("4", "No")]
