"""NoiseTrader: occasional random orders to keep the book ticking.

Per tick: 50/50 picks YES or NO outcome, 50/50 picks BUY or SELL side,
draws a random size from config bounds. With probability noise_aggressive_prob
the order is marketable (crosses the anchor band); otherwise it's a resting
order inside the band.
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
        self, *, market: MarketTokens, poly_yes_mid: float | None
    ) -> list[DesiredOrder]:
        if poly_yes_mid is None:
            return []
        rng = self._rng
        cfg = self._cfg

        is_yes = rng.random() < 0.5
        side = "BUY" if rng.random() < 0.5 else "SELL"
        token_id = market.yes_token_id if is_yes else market.no_token_id
        size_shares = rng.randint(cfg.noise_min_size_shares, cfg.noise_max_size_shares)

        # Anchor band — mirrors AnchorMarketMaker.
        mid = poly_yes_mid if is_yes else 1.0 - poly_yes_mid
        half = cfg.mm_half_spread_usd
        aggressive = rng.random() < cfg.noise_aggressive_prob

        if side == "BUY":
            if aggressive:
                # Cross the ask — lift it.
                price = _clip(mid + half + 0.005)
            else:
                price = _clip(mid - half - 0.005)
        else:
            if aggressive:
                price = _clip(mid - half - 0.005)
            else:
                price = _clip(mid + half + 0.005)

        return [DesiredOrder(
            side=side, token_id=token_id,
            price_int=int(round(price * PRICE_SCALE)),
            size=size_shares * SHARES_SCALE,
        )]
