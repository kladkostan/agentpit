"""Schema migration: new columns are present and round-trip via the DAL."""

import sqlite3

from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    return conn


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


from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState


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
    assert fetched.polymarket_yes_token_id == "111"
    assert fetched.polymarket_no_token_id == "222"
