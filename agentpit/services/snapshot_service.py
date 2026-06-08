"""Periodic mid-price snapshots for sparkline charts.

The home page sparkline needs price points over time even when no trades
have happened. We sample the orderbook mid on a fixed cadence and append
to a `price_snapshots` table; the sparkline endpoint then reads from
snapshots instead of trying to reconstruct history from sparse trades.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from agentpit.db.session import DbSession

log = logging.getLogger(__name__)


class SnapshotService:
    def __init__(self, db: DbSession):
        self._db = db

    def take_snapshot(self) -> int:
        """Sample YES-side mids for every ACTIVE market.

        Returns the number of rows inserted. Markets with empty books are
        skipped — the chart bridges the gap visually rather than recording
        nulls that the renderer would have to filter out anyway.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        inserted = 0
        with self._db.write() as conn:
            for market_id, token_id in _list_active_yes_tokens(conn):
                mid = _compute_mid(conn, token_id)
                if mid is None:
                    continue
                conn.execute(
                    "INSERT INTO price_snapshots "
                    "(MARKET_ID, ASSET_ID, T, MID_MICRO_USD) VALUES (%s, %s, %s, %s)",
                    (market_id, token_id, now, mid),
                )
                inserted += 1
        return inserted

    def prune_old(self, retention_seconds: int) -> int:
        """Delete snapshots older than the retention window."""
        cutoff = int(datetime.now(timezone.utc).timestamp()) - retention_seconds
        with self._db.write() as conn:
            cur = conn.execute(
                "DELETE FROM price_snapshots WHERE T < %s", (cutoff,)
            )
            return cur.rowcount


def _list_active_yes_tokens(conn) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT MARKET_ID, ERC1155_TOKENS FROM markets "
        "WHERE COALESCE(MARKET_STATE, 'DRAFT') = 'ACTIVE'"
    ).fetchall()
    out: list[tuple[int, str]] = []
    for r in rows:
        try:
            tokens = json.loads(r["ERC1155_TOKENS"]) if r["ERC1155_TOKENS"] else []
        except json.JSONDecodeError:
            log.warning("market %s has malformed ERC1155_TOKENS", r["MARKET_ID"])
            continue
        if tokens and tokens[0]:
            out.append((int(r["MARKET_ID"]), str(tokens[0][0])))
    return out


def _compute_mid(conn, token_id: str) -> int | None:
    """Best-bid/ask mid for a token, in micro-USDC. None if no live orders.

    Falls back to whichever side exists when the book is one-sided — same
    behavior as the frontend `computeMid` so the recorded mid matches what
    a user sees on the card.
    """
    row = conn.execute(
        "SELECT "
        "  MIN(CASE WHEN SIDE='SELL' THEN PRICE END) AS best_ask, "
        "  MAX(CASE WHEN SIDE='BUY' THEN PRICE END) AS best_bid "
        "FROM orders WHERE TOKEN_ID = %s AND STATUS = 'live'",
        (token_id,),
    ).fetchone()
    if row is None:
        return None
    best_ask = row["best_ask"]
    best_bid = row["best_bid"]
    if best_ask is not None and best_bid is not None:
        return (int(best_ask) + int(best_bid)) // 2
    if best_ask is not None:
        return int(best_ask)
    if best_bid is not None:
        return int(best_bid)
    return None
