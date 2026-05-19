"""Seed a populated orderbook on a target market.

Registers a handful of fresh users and posts a hand-picked sequence of BUY/SELL
limit orders on YES and NO so the page has a realistic-looking book.

The recipe:
  1. Two users place complementary BUY YES + BUY NO orders whose prices sum
     to >= 1.0 — the matcher triggers a MINT and delivers outcome shares to
     both users. (They now own shares and can post asks.)
  2. Several users post non-crossing BUY YES / BUY NO orders that rest as
     bids on both sides of the book.
  3. The two share-holders post SELL YES / SELL NO orders above the bid book
     and arranged so YES_ask + NO_ask > 1.0 (avoids MERGE matches).

Usage:
    python scripts/seed_market_orders.py --market 56
    python scripts/seed_market_orders.py --market 56 --base http://localhost:8000

Re-running is safe: emails are stamped with the current time so a fresh set of
users (seed-{name}-{stamp}@example.com) is created each run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


SHARES_SCALE = 1_000_000  # raw outcome-token units per display share


@dataclass
class User:
    name: str
    email: str
    token: str
    eth_address: str


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {body_text}") from None


def register_user(base: str, name: str, stamp: int) -> User:
    email = f"seed-{name}-{stamp}@example.com"
    res = _request(
        base,
        "/register",
        method="POST",
        body={"email": email, "password": "seedpass-12345"},
    )
    return User(
        name=name,
        email=email,
        token=res["access_token"],
        eth_address=res["user"]["eth_address"],
    )


def place_order(
    base: str,
    user: User,
    *,
    market_id: int,
    outcome: str,
    side: str,
    price: float,
    shares: int,
) -> dict[str, Any]:
    body = {
        "market_id": market_id,
        "outcome": outcome,
        "side": side,
        "price": str(Decimal(str(price))),
        "size": shares * SHARES_SCALE,
        "order_type": "GTC",
    }
    return _request(base, "/orders", method="POST", body=body, token=user.token)


def _label(side: str, outcome: str, price: float, shares: int) -> str:
    return f"{side:<4} {outcome:<3} {shares:>3} @ ${price:.2f}"


def seed(base: str, market_id: int) -> None:
    stamp = int(time.time())
    print(f"→ registering 5 users (stamp={stamp})")
    users: dict[str, User] = {}
    for name in ("alice", "bob", "carol", "dave", "eve"):
        user = register_user(base, name, stamp)
        users[name] = user
        print(f"   {name:<6} {user.email}  {user.eth_address}")

    # ---- Phase 1: complementary MINT to give alice YES + bob NO --------
    # alice's BUY YES @ 0.55 rests first; bob's BUY NO @ 0.50 triggers the
    # MINT match (sum 1.05 ≥ 1.0). After this, alice holds 80 YES and bob
    # holds 80 NO.
    print("\n→ phase 1: complementary MINT (alice YES + bob NO)")
    phase1: list[tuple[str, str, str, float, int]] = [
        ("alice", "BUY", "Yes", 0.55, 80),
        ("bob", "BUY", "No", 0.50, 80),
    ]
    for who, side, outcome, price, shares in phase1:
        res = place_order(
            base,
            users[who],
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            shares=shares,
        )
        filled = int(res["filledSize"]) / SHARES_SCALE
        print(
            f"   {who:<6} {_label(side, outcome, price, shares)}  → filled {filled:.0f}"
        )

    # ---- Phase 2: bid stack on both sides ------------------------------
    # All sums stay below 1.0 so nothing crosses. Carol/dave/eve provide
    # most of the depth; bob/alice add a few small bids too.
    print("\n→ phase 2: resting bids (BUY YES / BUY NO)")
    phase2: list[tuple[str, str, str, float, int]] = [
        ("carol", "BUY", "Yes", 0.28, 30),
        ("dave", "BUY", "Yes", 0.25, 40),
        ("eve", "BUY", "Yes", 0.22, 60),
        ("carol", "BUY", "Yes", 0.20, 25),
        ("dave", "BUY", "Yes", 0.18, 50),
        ("eve", "BUY", "Yes", 0.15, 100),
        ("eve", "BUY", "No", 0.70, 20),
        ("carol", "BUY", "No", 0.68, 25),
        ("dave", "BUY", "No", 0.65, 35),
        ("eve", "BUY", "No", 0.62, 40),
        ("carol", "BUY", "No", 0.60, 50),
        ("dave", "BUY", "No", 0.55, 60),
    ]
    for who, side, outcome, price, shares in phase2:
        res = place_order(
            base,
            users[who],
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            shares=shares,
        )
        status = res.get("status", "?")
        print(f"   {who:<6} {_label(side, outcome, price, shares)}  → {status}")

    # ---- Phase 3: ask stack from share holders -------------------------
    # alice posts YES asks; bob posts NO asks. Prices chosen so every
    # (YES_ask + NO_ask) pair sums to > 1.0 → no MERGE matches.
    print("\n→ phase 3: resting asks (SELL YES / SELL NO)")
    phase3: list[tuple[str, str, str, float, int]] = [
        ("alice", "SELL", "Yes", 0.32, 15),
        ("alice", "SELL", "Yes", 0.35, 25),
        ("alice", "SELL", "Yes", 0.40, 20),
        ("bob", "SELL", "No", 0.72, 15),
        ("bob", "SELL", "No", 0.75, 25),
        ("bob", "SELL", "No", 0.80, 20),
    ]
    for who, side, outcome, price, shares in phase3:
        res = place_order(
            base,
            users[who],
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            shares=shares,
        )
        status = res.get("status", "?")
        print(f"   {who:<6} {_label(side, outcome, price, shares)}  → {status}")

    print("\n✓ done — open /markets/{} to see the book".format(market_id))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--market", type=int, required=True, help="Target market_id")
    args = ap.parse_args()

    try:
        seed(args.base, args.market)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: cannot reach {args.base}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
