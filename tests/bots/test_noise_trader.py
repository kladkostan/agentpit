"""NoiseTrader generates a single random order per tick within size/price bounds."""
import random

from agentpit_bots.config import BotConfig, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.strategies.noise_trader import NoiseTrader
from agentpit_bots.strategies.base import MarketTokens


def _market():
    return MarketTokens(market_id=7, yes_token_id="yest", no_token_id="not")


def test_returns_one_order_within_size_bounds():
    cfg = BotConfig(noise_min_size_shares=5, noise_max_size_shares=10)
    strat = NoiseTrader(cfg, rng=random.Random(42))
    orders = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.5)
    assert len(orders) == 1
    o = orders[0]
    assert 5 * SHARES_SCALE <= o.size <= 10 * SHARES_SCALE
    assert o.side in {"BUY", "SELL"}
    assert o.token_id in {"yest", "not"}


def test_no_orders_when_mid_unknown():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []


def test_aggressive_mode_crosses_inside():
    """When aggressive_prob=1.0 the order should be marketable.

    For a BUY YES: price >= mid + half_spread (lifts asks).
    For a SELL YES: price <= mid - half_spread (hits bids).
    The fake config has mm_half_spread_usd=0.01 so anchor band is [0.49, 0.51]
    at mid=0.5. An aggressive BUY YES should price >= 0.51.
    """
    cfg = BotConfig(noise_aggressive_prob=1.0, mm_half_spread_usd=0.01)
    strat = NoiseTrader(cfg, rng=random.Random(1))
    # Force enough draws to see a YES side; run 20 iterations and check the
    # invariant on each marketable YES BUY.
    for _ in range(20):
        orders = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.5)
        if not orders:
            continue
        o = orders[0]
        if o.side == "BUY" and o.token_id == "yest":
            assert o.price_int >= int(0.51 * PRICE_SCALE)
        elif o.side == "SELL" and o.token_id == "yest":
            assert o.price_int <= int(0.49 * PRICE_SCALE)
