"""TDD specs for SnapshotService.

The service samples best-bid/ask mids on a cadence and appends them to the
`price_snapshots` table so the home-page sparkline can render a time series
even when no trades have happened. It also prunes rows past the retention
window to keep storage bounded.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate
from agentpit.db.table_write import TableWrite
from agentpit.services.snapshot_service import SnapshotService


@pytest.fixture()
def db_session() -> Any:
    session = DbSession(":memory:")
    with session.write() as conn:
        TableCreate.create_all_tables(conn)
    yield session
    session.close()


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(
    session: DbSession,
    *,
    question: str,
    cond_id: str,
    state: MarketState = MarketState.ACTIVE,
) -> Market:
    """Insert a binary market and return its full row.

    The first token is YES — same convention used by SnapshotService when
    deciding which side to sample.
    """
    req = CreateMarketRequest(
        question=question,
        description=f"d-{question}",
        erc1155_tokens=[(f"{cond_id}-y", "Yes"), (f"{cond_id}-n", "No")],
        slug=question.lower().replace(" ", "-").replace("?", ""),
        condition_id=ConditionId(cond_id),
        state=state,
    )
    with session.write() as conn:
        return TableWrite.create_market(conn, req, is_polygon_market=False)


def _seed_resting_order(
    session: DbSession,
    *,
    token_id: str,
    side: str,
    price_micro_usd: int,
    status: str = "live",
) -> None:
    """Insert a minimal `orders` row sufficient for mid computation.

    The snapshot service only reads TOKEN_ID, SIDE, PRICE, STATUS — every
    other column is left at its default so the helper stays small.
    """
    with session.write() as conn:
        conn.execute(
            "INSERT INTO orders (ORDER_ID, TOKEN_ID, SIDE, PRICE, STATUS) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"o-{token_id}-{side}-{price_micro_usd}", token_id, side, price_micro_usd, status),
        )


def _read_snapshots(session: DbSession) -> list[tuple[int, str, int, int]]:
    """Return all rows from price_snapshots as
    (market_id, asset_id, t, mid_micro_usd).
    """
    with session.read() as conn:
        rows = conn.execute(
            "SELECT MARKET_ID, ASSET_ID, T, MID_MICRO_USD FROM price_snapshots "
            "ORDER BY SNAPSHOT_ID"
        ).fetchall()
    return [(int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in rows]


# ----- take_snapshot ---------------------------------------------------------


def test_take_snapshot_inserts_one_row_per_active_market_with_book(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    _seed_resting_order(
        db_session, token_id=yes_token, side="BUY", price_micro_usd=400_000
    )
    _seed_resting_order(
        db_session, token_id=yes_token, side="SELL", price_micro_usd=600_000
    )

    service = SnapshotService(db_session)
    inserted = service.take_snapshot()

    assert inserted == 1
    snaps = _read_snapshots(db_session)
    assert len(snaps) == 1
    assert snaps[0][0] == market.market_id
    assert snaps[0][1] == yes_token


def test_take_snapshot_uses_midprice_of_best_bid_and_best_ask(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    # best bid = 480_000 (highest), best ask = 520_000 (lowest)
    _seed_resting_order(db_session, token_id=yes_token, side="BUY", price_micro_usd=400_000)
    _seed_resting_order(db_session, token_id=yes_token, side="BUY", price_micro_usd=480_000)
    _seed_resting_order(db_session, token_id=yes_token, side="SELL", price_micro_usd=520_000)
    _seed_resting_order(db_session, token_id=yes_token, side="SELL", price_micro_usd=600_000)

    SnapshotService(db_session).take_snapshot()

    snaps = _read_snapshots(db_session)
    assert snaps[0][3] == (480_000 + 520_000) // 2


def test_take_snapshot_uses_one_sided_price_when_only_asks_resting(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    _seed_resting_order(db_session, token_id=yes_token, side="SELL", price_micro_usd=700_000)

    SnapshotService(db_session).take_snapshot()

    snaps = _read_snapshots(db_session)
    assert snaps[0][3] == 700_000


def test_take_snapshot_uses_one_sided_price_when_only_bids_resting(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    _seed_resting_order(db_session, token_id=yes_token, side="BUY", price_micro_usd=300_000)

    SnapshotService(db_session).take_snapshot()

    snaps = _read_snapshots(db_session)
    assert snaps[0][3] == 300_000


def test_take_snapshot_skips_markets_with_no_resting_orders(db_session):
    _seed_market(db_session, question="A?", cond_id=_hex32("a"))

    inserted = SnapshotService(db_session).take_snapshot()

    assert inserted == 0
    assert _read_snapshots(db_session) == []


def test_take_snapshot_skips_non_live_orders(db_session):
    """A matched or cancelled order shouldn't count toward the mid."""
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    _seed_resting_order(
        db_session, token_id=yes_token, side="BUY", price_micro_usd=500_000, status="matched"
    )

    inserted = SnapshotService(db_session).take_snapshot()

    assert inserted == 0


def test_take_snapshot_skips_draft_markets(db_session):
    market = _seed_market(
        db_session, question="A?", cond_id=_hex32("a"), state=MarketState.DRAFT
    )
    yes_token = market.erc1155_tokens[0][0]
    _seed_resting_order(db_session, token_id=yes_token, side="BUY", price_micro_usd=500_000)
    _seed_resting_order(db_session, token_id=yes_token, side="SELL", price_micro_usd=520_000)

    inserted = SnapshotService(db_session).take_snapshot()

    assert inserted == 0


def test_take_snapshot_samples_yes_token_only(db_session):
    """Snapshot the first token (YES). NO is derivable client-side."""
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token, no_token = (
        market.erc1155_tokens[0][0],
        market.erc1155_tokens[1][0],
    )
    # Resting orders on the NO side only — YES book is empty.
    _seed_resting_order(db_session, token_id=no_token, side="BUY", price_micro_usd=200_000)
    _seed_resting_order(db_session, token_id=no_token, side="SELL", price_micro_usd=300_000)

    inserted = SnapshotService(db_session).take_snapshot()

    assert inserted == 0
    snaps = _read_snapshots(db_session)
    # If any rows did get inserted, they must be tagged with the YES token.
    for _, asset_id, _, _ in snaps:
        assert asset_id == yes_token


def test_take_snapshot_writes_each_active_market_independently(db_session):
    m_a = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    m_b = _seed_market(db_session, question="B?", cond_id=_hex32("b"))
    _seed_resting_order(
        db_session, token_id=m_a.erc1155_tokens[0][0], side="BUY", price_micro_usd=400_000
    )
    _seed_resting_order(
        db_session, token_id=m_a.erc1155_tokens[0][0], side="SELL", price_micro_usd=500_000
    )
    _seed_resting_order(
        db_session, token_id=m_b.erc1155_tokens[0][0], side="BUY", price_micro_usd=100_000
    )

    inserted = SnapshotService(db_session).take_snapshot()

    assert inserted == 2
    snaps = _read_snapshots(db_session)
    by_market = {s[0]: s[3] for s in snaps}
    assert by_market[m_a.market_id] == 450_000
    assert by_market[m_b.market_id] == 100_000


# ----- prune_old -------------------------------------------------------------


def test_prune_old_deletes_rows_older_than_retention_window(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    with db_session.write() as conn:
        conn.execute(
            "INSERT INTO price_snapshots (MARKET_ID, ASSET_ID, T, MID_MICRO_USD) "
            "VALUES (?, ?, ?, ?)",
            (market.market_id, yes_token, 1_000, 500_000),
        )
        conn.execute(
            "INSERT INTO price_snapshots (MARKET_ID, ASSET_ID, T, MID_MICRO_USD) "
            "VALUES (?, ?, strftime('%s','now'), ?)",
            (market.market_id, yes_token, 500_000),
        )

    deleted = SnapshotService(db_session).prune_old(retention_seconds=24 * 3600)

    assert deleted == 1
    snaps = _read_snapshots(db_session)
    # The recent row survives — the ancient one is gone.
    assert len(snaps) == 1


def test_prune_old_returns_zero_when_all_rows_are_within_retention(db_session):
    market = _seed_market(db_session, question="A?", cond_id=_hex32("a"))
    yes_token = market.erc1155_tokens[0][0]
    with db_session.write() as conn:
        conn.execute(
            "INSERT INTO price_snapshots (MARKET_ID, ASSET_ID, T, MID_MICRO_USD) "
            "VALUES (?, ?, strftime('%s','now'), ?)",
            (market.market_id, yes_token, 500_000),
        )

    deleted = SnapshotService(db_session).prune_old(retention_seconds=24 * 3600)

    assert deleted == 0
    assert len(_read_snapshots(db_session)) == 1
