"""Two-sided market maker anchored on Polymarket midpoint.

For each market the bot covers, quotes YES bid/ask around the upstream
mid and mirrors NO at (1 - mid) ± half_spread. Sizes and spread come
from BotConfig. Output is a list of DesiredOrder — pure function.
"""
from __future__ import annotations

from agentpit_bots.config import BotConfig, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.base import MarketTokens, Strategy

_MIN_PRICE = 0.01
_MAX_PRICE = 0.99


def _clip(x: float) -> float:
    return max(_MIN_PRICE, min(_MAX_PRICE, x))


def _price_int(p: float) -> int:
    return int(round(p * PRICE_SCALE))


class AnchorMarketMaker(Strategy):
    def __init__(self, cfg: BotConfig):
        self._cfg = cfg

    def compute_desired_orders(
        self, *, market: MarketTokens, poly_yes_mid: float | None
    ) -> list[DesiredOrder]:
        if poly_yes_mid is None:
            return []
        size = self._cfg.mm_quote_size_shares * SHARES_SCALE
        half = self._cfg.mm_half_spread_usd

        yes_bid = _clip(poly_yes_mid - half)
        yes_ask = _clip(poly_yes_mid + half)
        no_mid = 1.0 - poly_yes_mid
        no_bid = _clip(no_mid - half)
        no_ask = _clip(no_mid + half)

        return [
            DesiredOrder(side="BUY",  token_id=market.yes_token_id,
                         price_int=_price_int(yes_bid), size=size),
            DesiredOrder(side="SELL", token_id=market.yes_token_id,
                         price_int=_price_int(yes_ask), size=size),
            DesiredOrder(side="BUY",  token_id=market.no_token_id,
                         price_int=_price_int(no_bid), size=size),
            DesiredOrder(side="SELL", token_id=market.no_token_id,
                         price_int=_price_int(no_ask), size=size),
        ]
