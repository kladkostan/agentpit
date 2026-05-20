"""NoiseTrader: one resting order per tick at a distance-distributed price.

For each tick the strategy picks an outcome (YES/NO 50/50), a side
(BUY/SELL 50/50), and a distance ``d`` away from the outcome's anchor mid
drawn UNIFORMLY across the room between the mid and the price bound
(0.01/0.99) on that side. The price is placed at ``mid ± d`` and the order
size grows linearly with ``d`` (saturating far out), so resting depth is
thin at the spread and heavy in the tails — an inverted-gaussian book that
fills evenly to the edge on any market, without churning against the
anchor's tight quote at the spread.

SELL orders are dropped on the floor when the bot has < size of the
chosen outcome: fresh noise bots bootstrap by BUYing first.
"""

from __future__ import annotations

import random

from agentpit_bots.config import BotConfig, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.anchor_mm import (
    _MAX_PRICE,
    _MIN_PRICE,
    _clip,
    _price_int,
)
from agentpit_bots.strategies.base import MarketTokens, Strategy


class NoiseTrader(Strategy):
    def __init__(self, cfg: BotConfig, *, rng: random.Random | None = None):
        self._cfg = cfg
        self._rng = rng or random.Random()

    def compute_desired_orders(
        self,
        *,
        market: MarketTokens,
        poly_yes_mid: float | None,
        token_balances: dict[str, int] | None = None,
    ) -> list[DesiredOrder]:
        if poly_yes_mid is None:
            return []
        rng = self._rng
        cfg = self._cfg

        is_yes = rng.random() < 0.5
        side = "BUY" if rng.random() < 0.5 else "SELL"
        token_id = market.yes_token_id if is_yes else market.no_token_id

        anchor_mid = poly_yes_mid if is_yes else 1.0 - poly_yes_mid

        # Distance from this outcome's anchor mid, drawn UNIFORMLY across the
        # room between the mid and the price bound on the side we move: a BUY
        # rests at mid - d, a SELL at mid + d, and the book is bounded to
        # (0.01, 0.99). Sampling the distance as the full room (rather than an
        # absolute dollar amount) keeps the shape scale-invariant: on a skewed
        # market each side fills its own room out to the 0.01/0.99 edge instead
        # of overshooting and piling on the bound. A small min gap keeps orders
        # out of the anchor's tight quote.
        room = (anchor_mid - _MIN_PRICE) if side == "BUY" else (_MAX_PRICE - anchor_mid)
        if room <= 0:
            return []  # mid sits on the bound — no room to rest an order this side
        min_gap = min(cfg.noise_dist_min_usd, room)
        d = rng.uniform(min_gap, room)

        price = _clip(anchor_mid - d if side == "BUY" else anchor_mid + d)

        # Size grows with distance so the uniform spread of orders carries
        # heavy share-depth in the tails and thin depth at the spread — the
        # inverted-gaussian profile. It saturates at noise_dist_max_usd so the
        # far tail plateaus and the largest SELL stays within the noise seed
        # (see noise_inventory_split_shares). int() drops the fractional cent so
        # orders at the same cent share a size, keeping reconcile stable.
        d_cents = min(int(d * 100), int(cfg.noise_dist_max_usd * 100))
        size = (
            cfg.noise_size_base_shares + cfg.noise_size_per_cent * d_cents
        ) * SHARES_SCALE

        if side == "SELL":
            bal = (token_balances or {}).get(token_id, 0)
            if bal < size:
                return []

        return [
            DesiredOrder(
                side=side,
                token_id=token_id,
                price_int=_price_int(price),  # snapped to the 0.1¢ tick
                size=size,
            )
        ]
