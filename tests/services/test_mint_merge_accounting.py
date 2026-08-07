"""A trade row must name BOTH tokens that moved.

One ASSET_ID is enough for a NORMAL match, where both parties transact in the
same token. A MINT gives the maker the market's OTHER outcome and a MERGE
burns it, and nothing recorded that — so an account that mints could not have
its holdings reconstructed from its own trade history.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def test_the_trades_table_carries_both_tokens(db):
    """The columns exist and accept the two new values."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS) "
        "VALUES (%s, 'tok-a', 'tok-b', 'MINT', 'BUY', 400000, 100, 'matched')",
        (uuid.uuid4().hex,),
    )
    row = db.execute(
        "SELECT ASSET_ID, MAKER_ASSET_ID, MATCH_KIND FROM trades "
        "WHERE MATCH_KIND = 'MINT' LIMIT 1"
    ).fetchone()
    assert row["ASSET_ID"] == "tok-a"
    assert row["MAKER_ASSET_ID"] == "tok-b"
    assert row["MATCH_KIND"] == "MINT"


def test_the_columns_are_nullable_for_rows_written_before_they_existed(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, SIDE, PRICE, TRADE_SIZE, STATUS) "
        "VALUES (%s, 'tok-a', 'BUY', 400000, 100, 'matched')",
        (uuid.uuid4().hex,),
    )
    row = db.execute(
        "SELECT MAKER_ASSET_ID, MATCH_KIND FROM trades WHERE ASSET_ID='tok-a' "
        "AND MATCH_KIND IS NULL LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["MAKER_ASSET_ID"] is None


def test_maker_orders_payload_names_the_maker_token_not_the_takers():
    """`_insert_trade` used to copy the TAKER's token into the maker payload.
    For a mint that is the wrong token entirely — it is the one asset the
    maker did NOT receive."""
    import inspect

    from agentpit.services.order_service import OrderService

    src = inspect.getsource(OrderService._insert_trade)
    assert '"asset_id": token_id' not in src, (
        "the maker payload still claims the taker's token"
    )
    assert "maker_asset_id" in src
