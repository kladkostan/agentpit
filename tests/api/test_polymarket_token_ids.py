"""Schema migration: new columns are present and round-trip via the DAL."""

import sqlite3

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite

# Well-known Hardhat test private key (32 bytes, not a real secret).
_TEST_ETH_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_TEST_ETH_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    return conn


def _insert_user(conn: sqlite3.Connection, user_id: str = "u1", api_key: str = "ak") -> None:
    conn.execute(
        "INSERT INTO users (USER_ID, EMAIL, PASSWORD_HASH, ETH_ADDRESS, "
        "ETH_PRIVATE_KEY, API_KEY, CREATED_AT) VALUES "
        "(?, 'a@b', 'x', ?, ?, ?, 1)",
        (user_id, _TEST_ETH_ADDRESS, _TEST_ETH_PRIVATE_KEY, api_key),
    )


def test_markets_table_has_upstream_token_id_columns():
    conn = _make_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}
    assert "POLYMARKET_YES_TOKEN_ID" in cols
    assert "POLYMARKET_NO_TOKEN_ID" in cols


def test_users_table_has_is_bot_column():
    conn = _make_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "IS_BOT" in cols
    conn.execute(
        "INSERT INTO users (USER_ID, EMAIL, PASSWORD_HASH, ETH_ADDRESS, "
        "ETH_PRIVATE_KEY, API_KEY, CREATED_AT) VALUES "
        "('u1','a@b','x','0xabc','0xkey','ak',1)"
    )
    row = conn.execute("SELECT IS_BOT FROM users WHERE USER_ID='u1'").fetchone()
    assert row[0] == 0


def test_mark_user_as_bot_round_trip():
    conn = _make_db()
    _insert_user(conn, user_id="u1", api_key="ak")

    # Before marking: is_bot should be False
    user = TableRead.get_user_by_api_key(conn, "ak")
    assert user is not None
    assert user.is_bot is False

    # Mark as bot — should return True (row updated)
    result = TableWrite.mark_user_as_bot(conn, api_key="ak")
    assert result is True

    # After marking: is_bot should be True
    user = TableRead.get_user_by_api_key(conn, "ak")
    assert user is not None
    assert user.is_bot is True

    # Idempotent: a second call still returns True
    result2 = TableWrite.mark_user_as_bot(conn, api_key="ak")
    assert result2 is True

    # Non-existent api_key returns False
    result3 = TableWrite.mark_user_as_bot(conn, api_key="does_not_exist")
    assert result3 is False


def test_create_market_round_trips_upstream_token_ids():
    conn = _make_db()
    req = CreateMarketRequest(
        question="Q",
        description="D",
        polymarket_id=42,
        polymarket_condition_id="0xabc",
        polymarket_yes_token_id="111",
        polymarket_no_token_id="222",
        erc1155_tokens=[("0xaaa", "Yes"), ("0xbbb", "No")],
        slug="q",
        start_date=0,
        end_date=1,
        state=MarketState.ACTIVE,
        condition_id=ConditionId("0xabc"),
        outcome_label=None,
        icon_url=None,
    )
    market = TableWrite.create_market(conn, req, True)
    fetched = TableRead.read_market(conn, market.market_id)
    assert fetched is not None
    assert fetched.polymarket_yes_token_id == "111"
    assert fetched.polymarket_no_token_id == "222"


