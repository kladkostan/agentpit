"""Two-sided market maker anchored on Polymarket midpoint.

For each market the bot covers, quotes YES bid/ask around the upstream
mid and mirrors NO at (1 - mid) ± half_spread. Sizes and spread come
from BotConfig. Output is a list of DesiredOrder — pure function.
"""

from __future__ import annotations

from agentpit_bots.config import BotConfig, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.base import MarketTokens, Strategy

# Quote bounds. Set to the order engine's usable range (it accepts any
# 0 < p < 1) rather than a 1¢ floor: a 0.01 floor sat *above* the fair price
# on near-zero markets, so the anchor's bid clipped up (leaving residual drift)
# and noise couldn't bid at all (mid - 0.01 < 0 → no BUY room → empty bid side).
_MIN_PRICE = 0.001
_MAX_PRICE = 0.999

# Corrective orders sweep to the true Polymarket target; same engine bounds.
_ENGINE_MIN_PRICE = _MIN_PRICE
_ENGINE_MAX_PRICE = _MAX_PRICE


def _clip(x: float) -> float:
    return max(_MIN_PRICE, min(_MAX_PRICE, x))


# Minimum price increment: 0.1¢ = $0.001 = 1000 micro-USDC. The order engine
# rejects finer precision, so every quoted/corrected price snaps to this grid.
PRICE_TICK = 1000


def _price_int(p: float) -> int:
    return int(round(p * PRICE_SCALE / PRICE_TICK)) * PRICE_TICK


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

        orders: list[DesiredOrder] = []
        # Skip any outcome whose clipped quotes would self-cross — posting a
        # bid ≥ ask trades the bot against itself and drains its inventory.
        if yes_bid < yes_ask:
            orders.append(
                DesiredOrder(
                    side="BUY",
                    token_id=market.yes_token_id,
                    price_int=_price_int(yes_bid),
                    size=size,
                )
            )
            orders.append(
                DesiredOrder(
                    side="SELL",
                    token_id=market.yes_token_id,
                    price_int=_price_int(yes_ask),
                    size=size,
                )
            )
        if no_bid < no_ask:
            orders.append(
                DesiredOrder(
                    side="BUY",
                    token_id=market.no_token_id,
                    price_int=_price_int(no_bid),
                    size=size,
                )
            )
            orders.append(
                DesiredOrder(
                    side="SELL",
                    token_id=market.no_token_id,
                    price_int=_price_int(no_ask),
                    size=size,
                )
            )
        return orders

    def compute_correction_orders(
        self,
        *,
        market: MarketTokens,
        poly_yes_mid: float | None,
        yes_bids: list[tuple[int, int]],
        yes_asks: list[tuple[int, int]],
        no_bids: list[tuple[int, int]],
        no_asks: list[tuple[int, int]],
    ) -> list[DesiredOrder]:
        """Taker orders that pull each outcome's local price to its Polymarket
        target. Books are ``[(price_int, remaining_size), ...]``.

        For each token (YES → poly mid, NO → 1 - poly mid) the local price is
        "off" when either side of the book has drifted past tolerance:

        - too HIGH — the best bid OR the best ask sits above target + tol → SELL
          at the target, eating every bid above target (and resting the balance
          as the new best ask). This covers both an over-eager bid and a
          stranded high ask, which the bid-only rule used to miss.
        - too LOW  — the best ask OR the best bid sits below target - tol → BUY
          at the target, lifting every ask below target.

        The order price is the true target (clamped only to the engine's
        0.001/0.999 bounds), so near-0/1 markets converge to the real price even
        though the passive quote is skipped there. The tolerance is only the
        trigger; a market already within tol of target produces nothing.
        """
        if poly_yes_mid is None:
            return []
        tol = _price_int(self._cfg.mm_correction_tolerance_usd)
        max_size = self._cfg.mm_correction_max_shares * SHARES_SCALE
        # Minimum size when there are no crossing orders to eat — just enough to
        # plant a quote at the target so it becomes the new best price.
        plant = self._cfg.mm_quote_size_shares * SHARES_SCALE
        out: list[DesiredOrder] = []
        for token_id, target, bids, asks in (
            (market.yes_token_id, poly_yes_mid, yes_bids, yes_asks),
            (market.no_token_id, 1.0 - poly_yes_mid, no_bids, no_asks),
        ):
            t_int = _price_int(min(_ENGINE_MAX_PRICE, max(_ENGINE_MIN_PRICE, target)))
            best_bid = max((p for p, _ in bids), default=None)
            best_ask = min((p for p, _ in asks), default=None)

            # Too high: a bid or the whole ask side resting above target + tol.
            if (best_bid is not None and best_bid > t_int + tol) or (
                best_ask is not None and best_ask > t_int + tol
            ):
                cross = sum(sz for p, sz in bids if p > t_int)
                out.append(
                    DesiredOrder(
                        side="SELL",
                        token_id=token_id,
                        price_int=t_int,
                        size=min(cross or plant, max_size),
                    )
                )
            # Too low: an ask or the whole bid side resting below target - tol.
            if (best_ask is not None and best_ask < t_int - tol) or (
                best_bid is not None and best_bid < t_int - tol
            ):
                cross = sum(sz for p, sz in asks if p < t_int)
                out.append(
                    DesiredOrder(
                        side="BUY",
                        token_id=token_id,
                        price_int=t_int,
                        size=min(cross or plant, max_size),
                    )
                )
        return out
