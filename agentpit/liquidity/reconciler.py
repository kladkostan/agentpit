"""Diff a Polymarket BookSnapshot against the mirror account's live orders.

Pure functions in this module; the DB/chain applier (reconcile_market) is
added in a later task. Invariant (spec §5): desired levels derived from a
non-crossed snapshot are non-crossed per token AND across the YES/NO
complement map, so the mirror can never self-match — provided cancels are
applied before placements.
"""
from dataclasses import dataclass

from agentpit.liquidity.replica import MICRO, BookSnapshot


@dataclass(frozen=True)
class LiveLevel:
    order_id: str
    token_id: str
    side: str          # "BUY" | "SELL"
    price_micro: int
    size_micro: int    # REMAINING_AMOUNT


@dataclass(frozen=True)
class Placement:
    token_id: str
    side: str
    price_micro: int
    size_micro: int


def desired_levels(snap: BookSnapshot, yes_token: str, no_token: str) -> list[Placement]:
    """YES book verbatim + NO book as the exact 1-p complement (same sizes)."""
    out: list[Placement] = []
    for p, s in snap.bids:
        out.append(Placement(yes_token, "BUY", p, s))
        out.append(Placement(no_token, "SELL", MICRO - p, s))
    for p, s in snap.asks:
        out.append(Placement(yes_token, "SELL", p, s))
        out.append(Placement(no_token, "BUY", MICRO - p, s))
    return out


def diff_levels(
    desired: list[Placement], current: list[LiveLevel]
) -> tuple[list[str], list[Placement]]:
    """(order_ids to cancel, placements to make). Orders are immutable, so a
    size change at a level is cancel + re-place. One live order per
    (token, side, price) is kept; duplicates are cancelled."""
    want = {(d.token_id, d.side, d.price_micro): d.size_micro for d in desired}
    keep: set[tuple[str, str, int]] = set()
    cancels: list[str] = []
    for o in current:
        key = (o.token_id, o.side, o.price_micro)
        if key in want and want[key] == o.size_micro and key not in keep:
            keep.add(key)
        else:
            cancels.append(o.order_id)
    places = [
        Placement(token, side, price, size)
        for (token, side, price), size in want.items()
        if (token, side, price) not in keep
    ]
    return cancels, places


def split_target_micro(snap: BookSnapshot) -> int:
    """CTF inventory needed to back every SELL: YES asks need YES tokens, NO
    asks mirror the YES bid side. A split mints YES+NO equally, so the target
    is the max of the two ask-side sums (spec §8)."""
    yes_ask_sum = sum(s for _, s in snap.asks)
    no_ask_sum = sum(s for _, s in snap.bids)
    return max(yes_ask_sum, no_ask_sum)


def cap_sells_to_inventory(
    places: list[Placement], inventory_micro: dict[str, int]
) -> list[Placement]:
    """Drop SELL placements that exceed held CTF inventory, keeping the best
    (lowest-priced) asks. BUYs pass through (USDC is never the binding
    constraint). Result preserves no particular order."""
    remaining = dict(inventory_micro)
    out = [p for p in places if p.side == "BUY"]
    sells = sorted((p for p in places if p.side == "SELL"), key=lambda p: p.price_micro)
    for p in sells:
        held = remaining.get(p.token_id, 0)
        if p.size_micro <= held:
            remaining[p.token_id] = held - p.size_micro
            out.append(p)
    return out
