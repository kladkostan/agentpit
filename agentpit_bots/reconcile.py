"""Diff a bot's currently live orders against the strategy's desired set.

Pure function — no IO. The caller turns the returned cancels and creates
into REST calls.
"""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LiveOrder:
    order_id: str
    side: str  # "BUY" | "SELL"
    token_id: str
    price_int: int  # price scaled by 10^6
    remaining_amount: int


@dataclass(frozen=True)
class DesiredOrder:
    side: str
    token_id: str
    price_int: int
    size: int


def _key(side: str, token_id: str, price_int: int, size: int) -> tuple:
    return (side, token_id, price_int, size)


def reconcile(
    live: Iterable[LiveOrder],
    desired: Iterable[DesiredOrder],
) -> tuple[list[str], list[DesiredOrder]]:
    """Return ``(order_ids_to_cancel, desired_orders_to_create)``.

    An order is "matched" when its (side, token_id, price_int, size) tuple
    is shared between live and desired. Unmatched live → cancel.
    Unmatched desired → create.
    """
    live_list = list(live)
    desired_list = list(desired)
    desired_keys = {_key(d.side, d.token_id, d.price_int, d.size) for d in desired_list}
    live_keys = {
        _key(l.side, l.token_id, l.price_int, l.remaining_amount) for l in live_list
    }
    cancels = [
        l.order_id
        for l in live_list
        if _key(l.side, l.token_id, l.price_int, l.remaining_amount) not in desired_keys
    ]
    creates = [
        d
        for d in desired_list
        if _key(d.side, d.token_id, d.price_int, d.size) not in live_keys
    ]
    return cancels, creates
