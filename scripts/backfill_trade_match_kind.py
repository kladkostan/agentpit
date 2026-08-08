"""Fill `trades.MAKER_ASSET_ID` / `trades.MATCH_KIND` for rows written before
those columns existed.

This used to run inside `TableCreate.create_trades_table`, on every app
startup, before uvicorn bound its port. Benchmarked at 374,054 rows: 21.3s
(2.2s fetchall, 1.5s Python, 17.7s executemany) — all inside the ONE
transaction that also creates every other table, since `session.py` opens
with `autocommit=False`. `create_all_tables` has no error handling, so any
failure exits uvicorn; `restart: unless-stopped` then retries the whole
transaction from scratch, and nothing ever commits. That is 30-90s of hard
502s through Caddy on every deploy — and it would recur on every future
deploy too, since the liquidity tape writes new trade rows of its own
(`agentpit/liquidity/tape.py`) and the old in-process version could never
settle into a no-op.

This script does the same labelling, but out of band and in 10,000-row
commits instead of one. It only ever FILLS: it selects `WHERE MATCH_KIND IS
NULL`, so a row the write path already labelled is left untouched, and
running the script again after it finishes is a no-op.

The taker's side is on the row, the maker's is inside MAKER_ORDERS, and
those two decide the match kind exactly as the matcher decided it. The
maker's token is then the same asset for a NORMAL match, or the market's
other outcome for a MINT/MERGE — `markets.ERC1155_TOKENS` still holds the
pair. When that pair can't be resolved (a non-binary market, or a token no
market claims), MAKER_ASSET_ID is left NULL rather than guessing the taker's
asset: `AccountService._token_flow` already reads
`COALESCE(MAKER_ASSET_ID, ASSET_ID)`, so behaviour is unchanged — the row
just records "unknown" instead of asserting a token the maker never held.

    .venv/bin/python -m scripts.backfill_trade_match_kind [--dry-run]
"""

from __future__ import annotations

import argparse
import json

import psycopg

from agentpit.config import Settings
from agentpit.db.session import DbSession

#: Rows per UPDATE / commit. Keeps each transaction small instead of one
#: 374k-row transaction, and gives visible progress on a production run.
CHUNK = 10_000


def _complements(conn: psycopg.Connection) -> dict[str, str]:
    """`{token_id: the other outcome's token_id}` for every binary market —
    one read of `markets`, rather than one per trade row."""
    complements: dict[str, str] = {}
    for m in conn.execute("SELECT ERC1155_TOKENS FROM markets").fetchall():
        try:
            pairs = json.loads(m["ERC1155_TOKENS"])
        except (TypeError, ValueError):
            continue
        if len(pairs) != 2:
            continue
        a, b = pairs[0][0], pairs[1][0]
        complements[a] = b
        complements[b] = a
    return complements


def _compute_updates(
    rows: list, complements: dict[str, str]
) -> list[tuple[str | None, str, str]]:
    """`[(maker_asset_id, match_kind, trade_id), ...]` for a batch of rows
    selected with `SELECT TRADE_ID, ASSET_ID, SIDE, MAKER_ORDERS`."""
    updates: list[tuple[str | None, str, str]] = []
    for r in rows:
        taker_side = r["SIDE"]
        mo = r["MAKER_ORDERS"]
        try:
            parsed = json.loads(mo) if isinstance(mo, str) else mo
            maker_side = parsed[0].get("side") if parsed else None
        except (TypeError, ValueError, IndexError, KeyError, AttributeError):
            maker_side = None
        asset = r["ASSET_ID"]
        if taker_side == "BUY" and maker_side == "BUY":
            kind = "MINT"
        elif taker_side == "SELL" and maker_side == "SELL":
            kind = "MERGE"
        else:
            kind = "NORMAL"
        # A complement we cannot resolve (non-binary market, or a token no
        # market claims) is left NULL rather than falling back to the
        # taker's asset: `AccountService._token_flow` already reads
        # `COALESCE(MAKER_ASSET_ID, ASSET_ID)`, so behaviour is identical —
        # but the row then records "unknown" instead of asserting a token
        # the maker never actually held.
        maker_asset = asset if kind == "NORMAL" else complements.get(asset)
        updates.append((maker_asset, kind, r["TRADE_ID"]))
    return updates


def backfill_trade_match_kind(conn: psycopg.Connection) -> None:
    """Label every unlabelled row reachable from `conn`, in one pass.

    This is the primitive `main()` below drives in `CHUNK`-row commits for a
    production run; call sites with only a handful of rows (the test suite)
    can use it directly — one pass is already cheap enough that chunking
    would add nothing.
    """
    rows = conn.execute(
        "SELECT TRADE_ID, ASSET_ID, SIDE, MAKER_ORDERS FROM trades "
        "WHERE MATCH_KIND IS NULL"
    ).fetchall()
    if not rows:
        return
    updates = _compute_updates(rows, _complements(conn))
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE trades SET MAKER_ASSET_ID = %s, MATCH_KIND = %s "
            "WHERE TRADE_ID = %s",
            updates,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without touching the database",
    )
    args = parser.parse_args()

    # create_tables=False: the API has already migrated this database, and
    # re-running the DDL from a second process deadlocks against it — every
    # idempotent ADD COLUMN still takes an AccessExclusiveLock.
    db = DbSession(Settings().database_url, create_tables=False)
    with db.read() as conn:
        rows = conn.execute(
            "SELECT TRADE_ID, ASSET_ID, SIDE, MAKER_ORDERS FROM trades "
            "WHERE MATCH_KIND IS NULL"
        ).fetchall()
        updates = _compute_updates(rows, _complements(conn))

    mint = sum(1 for _, kind, _ in updates if kind == "MINT")
    merge = sum(1 for _, kind, _ in updates if kind == "MERGE")
    normal = sum(1 for _, kind, _ in updates if kind == "NORMAL")
    unresolved = sum(1 for maker_asset, _, _ in updates if maker_asset is None)
    print(
        f"{len(updates)} unlabelled trades: {normal} NORMAL, {mint} MINT, "
        f"{merge} MERGE ({unresolved} with an unresolved complement)"
        f"{' (dry run)' if args.dry_run else ''}"
    )

    if args.dry_run:
        print(f"done: {len(updates)} trades would be labelled")
    elif not updates:
        print("done: 0 trades labelled")
    else:
        labelled = 0
        for i in range(0, len(updates), CHUNK):
            batch = updates[i : i + CHUNK]
            with db.write() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE trades SET MAKER_ASSET_ID = %s, MATCH_KIND = %s "
                        "WHERE TRADE_ID = %s",
                        batch,
                    )
            labelled += len(batch)
            print(f"  {labelled}/{len(updates)} trades")
        print(f"done: {labelled} trades labelled")

    # Without this the pool's worker threads outlive main() and psycopg prints
    # a "couldn't stop thread" warning per worker on the way out.
    db.close()


if __name__ == "__main__":
    main()
