"""Seed orderbooks for every sub-market of an event.

Looks up the event via `GET /events/{slug}`, then runs the existing per-market
orderbook seeder (`scripts/seed_market_orders.py`) against each member market.
The per-market recipe (MINT + bid stack + ask stack) is unchanged — each
sub-market ends up with the same shape of book.

Usage:
    python scripts/seed_event_orders.py --event 2026-fifa-world-cup-winner-595
    python scripts/seed_event_orders.py --event drake-iceman --base http://localhost:8000
    python scripts/seed_event_orders.py --event wc --limit 5   # only first 5 markets

Re-running is safe: the per-market seeder mints fresh users on each invocation,
so orders accumulate across runs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PER_MARKET_SEEDER = REPO_ROOT / "scripts" / "seed_market_orders.py"


def fetch_event_market_ids(base: str, slug: str) -> list[int]:
    url = f"{base.rstrip('/')}/events/{slug}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"GET /events/{slug} → HTTP {e.code}: {body}") from None
    markets = payload.get("markets") or []
    return [int(m["market_id"]) for m in markets]


def seed_one(base: str, market_id: int) -> bool:
    """Run the per-market seeder. Returns True on success."""
    result = subprocess.run(
        [
            sys.executable,
            str(PER_MARKET_SEEDER),
            "--base",
            base,
            "--market",
            str(market_id),
        ],
    )
    return result.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--event", required=True, help="Event slug to seed")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only seed the first N sub-markets (0 = all)",
    )
    args = ap.parse_args()

    print(f"→ fetching event {args.event!r} from {args.base}")
    try:
        market_ids = fetch_event_market_ids(args.base, args.event)
    except (RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not market_ids:
        print(f"event has no sub-markets — nothing to seed", file=sys.stderr)
        return 1

    if args.limit > 0:
        market_ids = market_ids[: args.limit]
    print(f"→ seeding {len(market_ids)} market(s): {market_ids}")

    succeeded = 0
    failed: list[int] = []
    for mid in market_ids:
        print(f"\n══ market {mid} ══")
        if seed_one(args.base, mid):
            succeeded += 1
        else:
            failed.append(mid)
            print(f"   ✗ seeder exited non-zero for market {mid}", file=sys.stderr)

    print(f"\n✓ seeded {succeeded}/{len(market_ids)} market(s)")
    if failed:
        print(f"  failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
