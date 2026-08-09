"""The read paths that still told a MINT's story with the wrong token or the
wrong price. The money was already right — this is the narration of it."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _mint(db, *, asset="y", maker_asset="n", price=300_000, t=1000, size=100):
    """A MINT: taker BUYs `asset` at MICRO-price, maker BUYs `maker_asset` at
    price. The stored PRICE is the maker's."""
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,%s,%s,'MINT','BUY',%s,%s,'matched',%s,"
        "'tk','mk')",
        (uuid.uuid4().hex, asset, maker_asset, price, size, t),
    )


def test_the_batched_last_price_marks_the_taker_token_at_its_own_price(db):
    _mint(db, price=300_000)
    got = TableRead.last_trade_prices_for_tokens(db, ["y", "n"])
    assert got["y"] == 700_000
    assert got["n"] == 300_000, "the complement had no print at all before"


def test_the_batched_last_price_is_unchanged_for_a_normal_match(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME) "
        "VALUES (%s,'y','y','NORMAL','BUY',250000,100,'matched',1000)",
        (uuid.uuid4().hex,),
    )
    assert TableRead.last_trade_prices_for_tokens(db, ["y", "n"]) == {"y": 250_000}


def test_the_newest_print_wins_across_both_legs(db):
    """A later MINT on the complement must beat an earlier print on this
    token — the maker branch has to take part in the DISTINCT ON."""
    _mint(db, asset="a", maker_asset="b", price=200_000, t=1000)
    _mint(db, asset="b", maker_asset="a", price=900_000, t=2000)
    got = TableRead.last_trade_prices_for_tokens(db, ["a"])
    # At t=2000 token "a" was the MAKER's token, priced at the stored PRICE.
    assert got["a"] == 900_000
