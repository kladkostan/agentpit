import sqlite3
from unittest.mock import patch

import pytest

from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
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


def test_polymarket_to_erc1155_tokens_basic_conversion():
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


def test_polymarket_to_erc1155_tokens_empty_tokens():
    assert _polymarket_to_erc1155_tokens({"tokens": []}) == []


def test_polymarket_to_erc1155_tokens_missing_tokens_key():
    assert _polymarket_to_erc1155_tokens({}) == []


def test_polymarket_to_erc1155_tokens_multiple_outcomes():
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


def test_is_market_expired_expired_market():
    assert _is_market_expired({"end_date_iso": "2020-01-01T00:00:00Z"}) is True


def test_is_market_expired_future_market():
    assert _is_market_expired({"end_date_iso": "2099-12-31T23:59:59Z"}) is False


def test_is_market_expired_missing_end_date():
    assert _is_market_expired({}) is False


def test_is_market_expired_empty_end_date():
    assert _is_market_expired({"end_date_iso": ""}) is False


def test_is_market_expired_none_end_date():
    assert _is_market_expired({"end_date_iso": None}) is False


def test_is_market_expired_invalid_end_date():
    assert _is_market_expired({"end_date_iso": "not-a-date"}) is False


# ---------------------------------------------------------------------------
# fetch_all_polymarket_markets (Unit Tests)
# ---------------------------------------------------------------------------


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_default_query_params(mock_get):
    """Default call should request limit and offset."""
    mock_get.return_value = []
    fetch_all_polymarket_markets()
    url = mock_get.call_args[0][0]
    assert "limit=500" in url
    assert "offset=0" in url
    assert "archived=false" in url
    assert "active=true" in url
    assert "closed=false" in url


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_include_archived(mock_get):
    mock_get.return_value = []
    fetch_all_polymarket_markets(archived=True)
    url = mock_get.call_args[0][0]
    assert "archived=true" in url


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_include_closed(mock_get):
    mock_get.return_value = []
    fetch_all_polymarket_markets(closed=True)
    url = mock_get.call_args[0][0]
    assert "closed=true" in url


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_inactive(mock_get):
    mock_get.return_value = []
    fetch_all_polymarket_markets(active=False)
    url = mock_get.call_args[0][0]
    assert "active=false" in url


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_filters_expired_markets(mock_get):
    """Markets with end_date_iso in the past should be excluded."""
    mock_get.return_value = [
        {
            "condition_id": "0x" + "1" * 64,
            "question": "Expired",
            "end_date_iso": "2020-01-01T00:00:00Z",
            "archived": False,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        },
        {
            "condition_id": "0x" + "2" * 64,
            "question": "Active",
            "end_date_iso": "2099-12-31T00:00:00Z",
            "archived": False,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        },
        {
            "condition_id": "0x" + "3" * 64,
            "question": "No date",
            "archived": False,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        },
    ]
    result = fetch_all_polymarket_markets()
    questions = [m["question"] for m in result]
    assert "Expired" not in questions
    assert "Active" in questions
    assert "No date" in questions
    assert len(result) == 2


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_pagination(mock_get):
    """Test that it loops through pages using offset."""
    page1 = [
        {
            "condition_id": f"0x{i:064x}",
            "question": f"M{i}",
            "end_date_iso": "2099-12-31T00:00:00Z",
            "archived": False,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        }
        for i in range(1, 501)
    ]
    page2 = [
        {
            "condition_id": "0x" + "f" * 64,
            "question": "Last",
            "end_date_iso": "2099-12-31T00:00:00Z",
            "archived": False,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        }
    ]

    mock_get.side_effect = [page1, page2]
    result = fetch_all_polymarket_markets()
    assert len(result) == 501
    assert mock_get.call_count == 2
    assert "offset=0" in mock_get.call_args_list[0][0][0]
    assert "offset=500" in mock_get.call_args_list[1][0][0]


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_pagination_stops_on_empty_list(mock_get):
    mock_get.side_effect = [[]]
    result = fetch_all_polymarket_markets()
    assert len(result) == 0
    assert mock_get.call_count == 1


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_raises_on_leaked_archived_markets(mock_get):
    """Archived markets leaked by the API should raise an exception."""
    mock_get.return_value = [
        {
            "condition_id": "0x" + "a" * 64,
            "question": "Archived",
            "archived": True,
            "active": True,
            "closed": False,
            "liquidity": 2_000_000,
        },
    ]
    with pytest.raises(ValueError, match="returned archived market"):
        fetch_all_polymarket_markets(archived=False)


@patch("agentpit.polymarket.polymarket_sync.get")
def test_fetch_all_polymarket_markets_string_boolean_fields_are_normalized(mock_get):
    mock_get.return_value = [
        {
            "condition_id": "0x" + "b" * 64,
            "question": "Bool string market",
            "end_date_iso": "2099-12-31T00:00:00Z",
            "archived": "false",
            "active": "true",
            "closed": "false",
            "liquidity": "2000000",
            "tokens": [{"token_id": "1", "outcome": "Yes"}],
        }
    ]
    result = fetch_all_polymarket_markets()
    assert len(result) == 1
    assert result[0]["archived"] is False
    assert result[0]["active"] is True
    assert result[0]["closed"] is False


# ---------------------------------------------------------------------------
# fetch_polymarket_market (Integration Test)
# ---------------------------------------------------------------------------


def test_fetch_polymarket_market_fetches_real_market_by_id():
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


def test_fetch_polymarket_market_returns_none_for_nonexistent_market():
    """Test fetching a non-existent market returns None."""
    condition_id = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    market = fetch_polymarket_market(condition_id)
    assert market is None


def test_fetch_polymarket_market_returns_none_for_invalid_id():
    """Test fetching with a badly formatted ID returns None."""
    market = fetch_polymarket_market("not-a-valid-id")
    assert market is None



# ---------------------------------------------------------------------------
# fetch_all_polymarket_markets (Integration Test)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fetch_all_polymarket_markets_fetches_real_markets():
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
def test_sync_polymarket_markets_syncs_real_markets_to_db(db):
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
    assert len(first_db.erc1155_tokens) > 0

    # now do it again as an update
    created_markets = sync_polymarket_markets(db)

    assert created_markets == []  # No new markets should be created on second sync
