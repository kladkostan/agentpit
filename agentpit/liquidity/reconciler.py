"""Diff a Polymarket BookSnapshot against the mirror account's live orders.

Pure functions first; the DB/chain applier (reconcile_market) follows them.
Invariant (spec §5): desired levels derived from a non-crossed snapshot are
non-crossed per token AND across the YES/NO complement map, so the mirror can
never self-match — provided cancels are applied before placements.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity.replica import MICRO, BookSnapshot
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


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
    """Fill SELL placements lowest-price-first, skipping any that exceed
    remaining per-token inventory (greedy best-effort — a too-big best ask is
    dropped, smaller worse-priced asks may still fit). BUYs pass through (USDC
    is never the binding constraint). Result preserves no particular order."""
    remaining = dict(inventory_micro)
    out = [p for p in places if p.side == "BUY"]
    sells = sorted((p for p in places if p.side == "SELL"), key=lambda p: p.price_micro)
    for p in sells:
        held = remaining.get(p.token_id, 0)
        if p.size_micro <= held:
            remaining[p.token_id] = held - p.size_micro
            out.append(p)
    return out


def _ensure_inventory(
    onchain: OnchainAdmin, user: User, ref, snap: BookSnapshot, cfg: Settings
) -> int:
    """Split-mint CTF inventory up to the snapshot's ask-side need × buffer.
    Returns the number of split txs performed (0 or 1 per call — splits are
    admin txs behind the global send_lock, budgeted by the caller)."""
    need = int(split_target_micro(snap) * cfg.mirror_inventory_buffer)
    if need <= 0:
        return 0
    held_yes = onchain.ctf_balance(user.eth_address, int(ref.yes_token))
    held_no = onchain.ctf_balance(user.eth_address, int(ref.no_token))
    add = need - min(held_yes, held_no)
    if add <= 0:
        return 0
    condition_bytes = bytes.fromhex(ref.condition_id[2:])
    onchain.user_split_position(user.eth_key, condition_bytes, add)
    return 1


def _crosses(p: Placement, foreign_bid: int | None, foreign_ask: int | None) -> bool:
    if p.side == "BUY":
        return foreign_ask is not None and p.price_micro >= foreign_ask
    return foreign_bid is not None and p.price_micro <= foreign_bid


def reconcile_market(
    db: DbSession,
    order: OrderService,
    onchain: OnchainAdmin,
    user: User,
    ref,                       # feed.MarketRef (duck-typed to avoid an import cycle)
    snap: BookSnapshot,
    cfg: Settings,
) -> dict:
    """Converge the local books (YES + NO complement) to the snapshot.
    Cancels strictly before placements (spec §5). Placements that would cross
    a NON-house order are intentional bot fills (spec §7) — they run last,
    capped at cfg.mirror_max_settlements_per_cycle real settlements."""
    tokens = [ref.yes_token, ref.no_token]
    with db.read() as conn:
        rows = TableRead.list_live_order_levels(conn, user.api_key, tokens)
        foreign = {t: TableRead.foreign_touch(conn, user.api_key, t) for t in tokens}
    current = [
        LiveLevel(r["ORDER_ID"], r["TOKEN_ID"], r["SIDE"],
                  int(r["PRICE"]), int(r["REMAINING_AMOUNT"]))
        for r in rows
    ]
    cancels, places = diff_levels(desired_levels(snap, ref.yes_token, ref.no_token),
                                  current)

    splits = 0
    try:
        splits = _ensure_inventory(onchain, user, ref, snap, cfg)
    except Exception:
        log.exception("inventory split failed for market %s", ref.market_id)
    inventory = {
        ref.yes_token: onchain.ctf_balance(user.eth_address, int(ref.yes_token)),
        ref.no_token: onchain.ctf_balance(user.eth_address, int(ref.no_token)),
    }
    places = cap_sells_to_inventory(places, inventory)

    if cancels:
        order.cancel_orders(user, cancels)

    # Non-crossing placements first; crossing ones (real settlements) last + capped.
    calm = [p for p in places if not _crosses(p, *foreign[p.token_id])]
    hot = [p for p in places if _crosses(p, *foreign[p.token_id])]
    placed = fills = 0
    for p in calm + hot:
        if p in hot and fills >= cfg.mirror_max_settlements_per_cycle:
            continue           # defer to a later cycle — keeps the loop unblocked
        resp = order.place_order(user, PlaceOrderRequest(
            token_id=p.token_id, side=p.side,
            price=Decimal(p.price_micro) / MICRO,
            size=Decimal(p.size_micro) / MICRO,
            order_type="GTC",
        ))
        if not resp.success:
            log.warning("mirror placement settlement failed (market=%s %s@%s): %s",
                        ref.market_id, p.side, p.price_micro, resp.errorMsg)
            continue
        placed += 1
        if resp.tradeIDs:
            fills += 1
            if p in calm:
                log.error("mirror placement unexpectedly filled — foreign-touch "
                          "guard missed (market=%s %s@%s)",
                          ref.market_id, p.side, p.price_micro)
    return {"placed": placed, "cancelled": len(cancels), "fills": fills,
            "splits": splits}
