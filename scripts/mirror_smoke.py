#!/usr/bin/env python3
# scripts/mirror_smoke.py
"""60-second live capture from the Polymarket WSS market channel.

Usage:
    python scripts/mirror_smoke.py <YES_TOKEN_ID> [<YES_TOKEN_ID> ...]

Prints per-event-type counts, replica convergence stats, and — the open spec
question (§9/§13.3) — whether last_trade_price events for the SIBLING (NO)
asset arrive on a YES-only subscription.
"""
import asyncio
import json
import sys
from collections import Counter

import websockets

from agentpit.liquidity.feed import WSS_URL, parse_events
from agentpit.liquidity.replica import BookReplica


async def main(asset_ids: list[str], duration: float = 60.0) -> None:
    counts: Counter = Counter()
    trade_assets: Counter = Counter()
    replicas = {a: BookReplica(a) for a in asset_ids}
    async with websockets.connect(WSS_URL) as ws:
        await ws.send(json.dumps({"assets_ids": asset_ids, "type": "market"}))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        while loop.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except TimeoutError:
                await ws.send("PING")
                continue
            for ev in parse_events(raw):
                et = ev.get("event_type", "?")
                counts[et] += 1
                if et == "book" and ev.get("asset_id") in replicas:
                    replicas[ev["asset_id"]].apply_book(ev)
                elif et == "price_change":
                    for e in ev.get("price_changes") or []:
                        rep = replicas.get(e.get("asset_id"))
                        if rep is not None:
                            rep.apply_price_change_entry(e)
                elif et == "last_trade_price":
                    a = ev.get("asset_id", "?")
                    trade_assets["subscribed" if a in replicas else "sibling"] += 1

    print("event counts:", dict(counts))
    print("last_trade_price by origin:", dict(trade_assets))
    print("=> sibling>0 means NO-side trades DO arrive on a YES-only subscription")
    for a, r in replicas.items():
        snap = r.snapshot()
        print(f"{a[:16]}…: seeded={r.seeded} levels="
              f"{len(snap.bids) if snap else 0}+{len(snap.asks) if snap else 0}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1:]))
