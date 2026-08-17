#!/usr/bin/env python3
"""Seed the price chart from Polymarket's own history.

The chart on a market page is drawn from prints in `trades`, which only exist
where something actually matched here. After a fresh deployment that is almost
nowhere, so every market reads "no price history yet" however healthy its book
is. This backfills the missing past the same way the live tape fills the
present: by mirroring Polymarket.

What it writes is not invented. Each point is a real price Polymarket recorded
for that outcome, inserted under `MIRROR_API_KEY` exactly like a live mirrored
print, with `TRADE_SIZE = 0` so a backfilled chart never becomes backfilled
volume.

The NO side is derived as `1 - p` rather than fetched. That halves the requests
and, more importantly, guarantees the two sides of a market cannot disagree --
two independent fetches taken seconds apart can, and a book that sums to 1.003
is worse than one point of staleness.

Idempotent: trade ids are deterministic (`pmhist-<token>-<t>`), so a second run
inserts nothing. Undo with
`DELETE FROM trades WHERE TRADE_ID LIKE 'pmhist-%'`.

Usage (inside the api container, which already has the deps and the DSN):
    python scripts/backfill_price_history.py [--interval 1w] [--fidelity 60]
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, "/app")

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.liquidity.tape import MIRROR_API_KEY

CLOB_HISTORY = "https://clob.polymarket.com/prices-history"
MICRO = 1_000_000


def fetch(client: httpx.Client, pm_token: str, interval: str, fidelity: int):
    """Polymarket's history for one token, or [] if it has none.

    A market we mirror but they have never priced is normal, not an error, and
    one such market must not abort a run over hundreds.
    """
    try:
        resp = client.get(
            CLOB_HISTORY,
            params={"market": pm_token, "interval": interval, "fidelity": fidelity},
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json().get("history") or []
    except Exception as exc:  # noqa: BLE001 - one bad token must not stop the run
        print(f"  skip {pm_token[:12]}...: {exc}", file=sys.stderr)
        return []


def local_tokens(erc1155_tokens: str) -> "tuple[str | None, str | None]":
    """(yes_local_id, no_local_id) out of the stored [[id, label], ...] JSON."""
    try:
        pairs = json.loads(erc1155_tokens)
    except (TypeError, ValueError):
        return None, None
    by_label = {str(label).lower(): str(tid) for tid, label in pairs}
    return by_label.get("yes"), by_label.get("no")


def rows_for(market, points) -> list:
    """One print per point per side, shaped like a live mirrored trade."""
    condition_id, yes_local, no_local = market
    out = []
    for pt in points:
        t = int(pt["t"])
        p = float(pt["p"])
        yes_micro = max(0, min(MICRO, round(p * MICRO)))
        for token, price in ((yes_local, yes_micro), (no_local, MICRO - yes_micro)):
            if not token:
                continue
            out.append((
                f"pmhist-{token}-{t}", "", "[]", condition_id, token, token,
                "NORMAL", price, 0, 0, "BUY", "MATCHED", t, "", 0, 0,
                MIRROR_API_KEY, MIRROR_API_KEY,
            ))
    return out


INSERT = """
    INSERT INTO trades (
        TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
        MAKER_ASSET_ID, MATCH_KIND, PRICE, TRADE_SIZE, REMAINING_SIZE,
        SIDE, STATUS, MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX,
        FEE_RATE_BPS, TAKER_API_KEY, MAKER_API_KEY
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1w")
    ap.add_argument("--fidelity", type=int, default=60, help="minutes between points")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    db = DbSession(Settings().database_url, create_tables=False)
    with db.read() as conn:
        markets = conn.execute(
            "SELECT POLYMARKET_CONDITION_ID, POLYMARKET_YES_TOKEN_ID, ERC1155_TOKENS "
            "FROM markets WHERE MARKET_STATE = 'ACTIVE' "
            "AND POLYMARKET_YES_TOKEN_ID IS NOT NULL"
        ).fetchall()
    print(f"{len(markets)} active markets to backfill")

    jobs = []
    for r in markets:
        yes_local, no_local = local_tokens(r["ERC1155_TOKENS"])
        if not yes_local:
            continue
        jobs.append((
            str(r["POLYMARKET_YES_TOKEN_ID"]),
            (str(r["POLYMARKET_CONDITION_ID"]), yes_local, no_local),
        ))

    written = 0
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            histories = list(pool.map(
                lambda j: fetch(client, j[0], args.interval, args.fidelity), jobs
            ))
        for (_, market), points in zip(jobs, histories):
            rows = rows_for(market, points)
            if not rows:
                continue
            with db.write() as conn:
                with conn.cursor() as cur:
                    cur.executemany(INSERT, rows)
            written += len(rows)
            print(f"  {market[1][:10]}... {len(rows)} prints", flush=True)

    print(f"done: {written} prints written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
