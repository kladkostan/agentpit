"""NoiseTrader: one resting order per tick at a distance-distributed price.

For each tick the strategy picks an outcome (YES/NO 50/50), a side
(BUY/SELL 50/50), and a distance ``d`` (in USD) away from the outcome's
anchor mid drawn from a clipped exponential. The price is placed at
``mid ± d`` and the order size grows linearly with ``d`` so that
far-out orders are both more numerous (over time) and larger — building
visible depth in the orderbook tail without churning against the anchor's
tight quote at the spread.

SELL orders are dropped on the floor when the bot has < size of the
chosen outcome: fresh noise bots bootstrap by BUYing first.
"""
from __future__ import annotations

import random

from agentpit_bots.config import BotConfig, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.anchor_mm import _clip
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

        # Distance from this outcome's anchor mid, drawn from a triangular
        # distribution over [min, max] peaked at `mode`. With mode == max
        # density ramps up toward the far edge, so most resting depth lands
        # away from the anchor's spread instead of crowding it. Mode is
        # clamped into [min, max] — random.triangular doesn't enforce this
        # and would otherwise emit out-of-range samples.
        lo, hi = cfg.noise_dist_min_usd, cfg.noise_dist_max_usd
        mode = max(lo, min(hi, cfg.noise_dist_mode_usd))
        d = rng.triangular(lo, hi, mode)

        anchor_mid = poly_yes_mid if is_yes else 1.0 - poly_yes_mid
        price = anchor_mid - d if side == "BUY" else anchor_mid + d
        price = _clip(price)

        # int(d * 100) drops the fractional cent so two orders at exactly the
        # same cent share a size — keeps reconcile-by-(price, size) stable.
        d_cents = int(d * 100)
        size = (cfg.noise_size_base_shares + cfg.noise_size_per_cent * d_cents) * SHARES_SCALE

        if side == "SELL":
            bal = (token_balances or {}).get(token_id, 0)
            if bal < size:
                return []

        return [DesiredOrder(
            side=side, token_id=token_id,
            price_int=int(round(price * PRICE_SCALE)),
            size=size,
        )]
