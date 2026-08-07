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


# ----- backfilling rows written before the columns existed --------------------

from agentpit.datastructures.condition_id import ConditionId  # noqa: E402
from agentpit.datastructures.create_market_request import (  # noqa: E402
    CreateMarketRequest,
)
from agentpit.datastructures.market_state import MarketState  # noqa: E402
from agentpit.db.table_create import TableCreate  # noqa: E402
from agentpit.db.table_write import TableWrite  # noqa: E402


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _binary_market(db, seed: str):
    """A two-outcome market whose tokens are `<seed>-y` and `<seed>-n`."""
    return TableWrite.create_market(
        db,
        CreateMarketRequest(
            question=f"{seed}?",
            description="d",
            erc1155_tokens=[(f"{seed}-y", "Yes"), (f"{seed}-n", "No")],
            slug=seed,
            condition_id=ConditionId(_hex32(seed)),
            state=MarketState.ACTIVE,
        ),
        is_polygon_market=False,
    )


def _legacy_trade(db, *, market, asset, taker_side, maker_side):
    """A row in the pre-column shape: no MAKER_ASSET_ID, no MATCH_KIND."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, SIDE, PRICE, "
        "TRADE_SIZE, STATUS, MAKER_ORDERS) "
        "VALUES (%s, %s, %s, %s, 400000, 100, 'matched', %s)",
        (
            uuid.uuid4().hex,
            market.condition_id.value,
            asset,
            taker_side,
            json.dumps([{"side": maker_side, "asset_id": asset}]),
        ),
    )


def _kinds(db):
    rows = db.execute(
        "SELECT ASSET_ID, MAKER_ASSET_ID, MATCH_KIND FROM trades "
        "WHERE MATCH_KIND IS NOT NULL ORDER BY ASSET_ID"
    ).fetchall()
    return [(r["ASSET_ID"], r["MAKER_ASSET_ID"], r["MATCH_KIND"]) for r in rows]


def test_backfill_labels_a_normal_match_and_keeps_one_token(db):
    m = _binary_market(db, "bfn")
    _legacy_trade(db, market=m, asset="bfn-y", taker_side="BUY", maker_side="SELL")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfn-y", "bfn-y", "NORMAL")]


def test_backfill_gives_a_mint_maker_the_complementary_token(db):
    """Both sides buying is a mint: the maker receives the OTHER outcome."""
    m = _binary_market(db, "bfm")
    _legacy_trade(db, market=m, asset="bfm-y", taker_side="BUY", maker_side="BUY")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfm-y", "bfm-n", "MINT")]


def test_backfill_gives_a_merge_maker_the_complementary_token(db):
    """Both sides selling is a merge: the maker burns the OTHER outcome."""
    m = _binary_market(db, "bfg")
    _legacy_trade(db, market=m, asset="bfg-n", taker_side="SELL", maker_side="SELL")
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == [("bfg-n", "bfg-y", "MERGE")]


def test_backfill_leaves_already_labelled_rows_alone(db):
    """Idempotent: it only fills rows the columns never reached."""
    m = _binary_market(db, "bfi")
    db.execute(
        "INSERT INTO trades (TRADE_ID, MARKET, ASSET_ID, MAKER_ASSET_ID, "
        "MATCH_KIND, SIDE, PRICE, TRADE_SIZE, STATUS, MAKER_ORDERS) "
        "VALUES (%s, %s, 'bfi-y', 'DELIBERATE', 'NORMAL', 'BUY', 1, 1, "
        "'matched', %s)",
        (uuid.uuid4().hex, m.condition_id.value,
         json.dumps([{"side": "BUY"}])),
    )
    TableCreate.backfill_trade_match_kind(db)
    # Were it re-derived, the BUY/BUY pair would relabel this MINT.
    assert _kinds(db) == [("bfi-y", "DELIBERATE", "NORMAL")]


def test_backfill_is_a_no_op_on_a_second_run(db):
    m = _binary_market(db, "bft")
    _legacy_trade(db, market=m, asset="bft-y", taker_side="BUY", maker_side="BUY")
    TableCreate.backfill_trade_match_kind(db)
    first = _kinds(db)
    TableCreate.backfill_trade_match_kind(db)
    assert _kinds(db) == first
