"""A price print is "this token traded at this price".

A NORMAL match yields exactly ONE print — both parties trade the same token at
the same price, and emitting both legs would double every chart point and every
volume figure derived from the tape. A MINT/MERGE yields TWO, on different
tokens, whose prices sum to MICRO.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from agentpit.datastructures.match_leg import MICRO, legs_for_user
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _trade(db, *, asset, maker_asset, kind, side, price, size=100, t=1000):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME, TAKER_API_KEY, "
        "MAKER_API_KEY) VALUES (%s,%s,%s,%s,%s,%s,%s,'matched',%s,'tk','mk')",
        (uuid.uuid4().hex, asset, maker_asset, kind, side, price, size, t),
    )


def _prints(db, tokens):
    rows = db.execute(
        TableRead.TOKEN_PRINTS_CTE
        + "SELECT TOKEN_ID, MATCH_TIME, PRICE, TRADE_SIZE, SIDE FROM prints "
          "ORDER BY TOKEN_ID, MATCH_TIME",
        (list(tokens), list(tokens)),
    ).fetchall()
    return [(r["TOKEN_ID"], int(r["PRICE"]), r["SIDE"]) for r in rows]


def test_a_normal_match_yields_exactly_one_print(db):
    """The double-counting trap: a NORMAL maker trades the SAME token at the
    SAME price, so its leg is not a second print."""
    _trade(db, asset="y", maker_asset="y", kind="NORMAL", side="BUY", price=250_000)
    assert _prints(db, ["y", "n"]) == [("y", 250_000, "BUY")]


def test_a_mint_yields_a_print_on_each_token_summing_to_one_dollar(db):
    _trade(db, asset="y", maker_asset="n", kind="MINT", side="BUY", price=300_000)
    got = _prints(db, ["y", "n"])
    assert got == [("n", 300_000, "BUY"), ("y", 700_000, "BUY")]
    assert sum(p for _, p, _ in got) == MICRO


def test_a_merge_prints_a_sell_on_each_token(db):
    _trade(db, asset="y", maker_asset="n", kind="MERGE", side="SELL", price=400_000)
    got = _prints(db, ["y", "n"])
    assert got == [("n", 400_000, "SELL"), ("y", 600_000, "SELL")]


def test_a_null_match_kind_takes_the_normal_path(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, SIDE, PRICE, TRADE_SIZE, "
        "STATUS, MATCH_TIME) VALUES (%s,'y','BUY',250000,100,'matched',1000)",
        (uuid.uuid4().hex,),
    )
    assert _prints(db, ["y"]) == [("y", 250_000, "BUY")]


def test_a_mint_with_unresolved_complement_suppresses_the_maker_print(db):
    """MAKER_ASSET_ID can be NULL on a MINT/MERGE row: commit 9b374f5 made the
    backfill record "unknown" rather than assert a token the maker never
    held, when the complement could not be resolved. The maker branch's
    `MAKER_ASSET_ID IS NOT NULL` guard excludes that row, so only the taker's
    print survives — we cannot name the token the maker received, and a print
    at the maker's price on the TAKER's token would be a false price, which
    is worse than a missing one.

    Deliberately NOT folded into test_the_sql_and_the_python_truth_table_agree:
    `legs_for_user` COALESCEs a NULL MAKER_ASSET_ID back to ASSET_ID, so the
    position layer books the maker's leg on the taker's token — a position
    must account for size that genuinely moved even when the token is
    unknown. The print layer has no such obligation and suppresses it
    instead. That divergence between the two layers is intentional; do not
    "fix" one into matching the other.
    """
    _trade(db, asset="y", maker_asset=None, kind="MINT", side="BUY", price=300_000)
    assert _prints(db, ["y", "n"]) == [("y", 700_000, "BUY")]


def test_a_failed_trade_never_prints(db):
    db.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, MAKER_ASSET_ID, MATCH_KIND, "
        "SIDE, PRICE, TRADE_SIZE, STATUS, MATCH_TIME) "
        "VALUES (%s,'y','n','MINT','BUY',300000,100,'FAILED',1000)",
        (uuid.uuid4().hex,),
    )
    assert _prints(db, ["y", "n"]) == []


def test_the_sql_and_the_python_truth_table_agree(db):
    """The two representations encode the same domain in two languages. This
    is what stops them drifting — silently, months from now.

    The bridge between them: a token's print is the leg of the party whose
    OWN token it is — the taker for ASSET_ID, the maker for MAKER_ASSET_ID.
    For a NORMAL match both legs sit on one token and the print is the
    taker's, which is exactly why NORMAL yields one print and not two.
    """
    cases = [
        ("NORMAL", "BUY", 250_000, "y"),
        ("NORMAL", "SELL", 250_000, "y"),
        ("MINT", "BUY", 300_000, "n"),
        ("MERGE", "SELL", 400_000, "n"),
    ]
    for kind, side, price, maker_asset in cases:
        db.execute("DELETE FROM trades")
        _trade(db, asset="y", maker_asset=maker_asset, kind=kind, side=side,
               price=price)
        row = db.execute(
            "SELECT TAKER_API_KEY, MAKER_API_KEY, ASSET_ID, MAKER_ASSET_ID, "
            "MATCH_KIND, SIDE, PRICE, TRADE_SIZE FROM trades"
        ).fetchone()
        taker_leg = legs_for_user(row, "tk")[0]
        maker_leg = legs_for_user(row, "mk")[0]
        expected = {taker_leg.token_id: (taker_leg.price_micro, taker_leg.side)}
        if kind in ("MINT", "MERGE"):
            expected[maker_leg.token_id] = (
                maker_leg.price_micro, maker_leg.side
            )
        got = {t: (p, s) for t, p, s in _prints(db, ["y", "n"])}
        assert got == expected, kind


def test_both_token_columns_are_indexed(db):
    """Without these the tape seq-scans the whole table on every chart load —
    measured at 132 ms over 458k rows to return 21 points."""
    names = {
        r["INDEXNAME"]
        for r in db.execute(
            "SELECT indexname AS INDEXNAME FROM pg_indexes WHERE tablename='trades'"
        ).fetchall()
    }
    assert "idx_trades_asset_id" in names
    assert "idx_trades_maker_asset_id" in names


def test_the_maker_asset_id_index_is_partial(db):
    """The maker branch is gated on MATCH_KIND IN ('MINT', 'MERGE'), so a
    full index would carry an entry for every mirrored row (373k of 458k in
    production) that branch can never return. Without the predicate the
    planner falls back to a Bitmap Heap Scan instead of an Index Scan."""
    row = db.execute(
        "SELECT indexdef AS INDEXDEF FROM pg_indexes "
        "WHERE tablename='trades' AND indexname='idx_trades_maker_asset_id'"
    ).fetchone()
    assert row is not None
    assert "MATCH_KIND" in row["INDEXDEF"].upper()
