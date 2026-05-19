"""NoiseTrader emits one resting order per tick at a distance-distributed
price away from the outcome's anchor mid. Distance from mid is sampled
from a clipped exponential; size grows with distance."""
import random

from agentpit_bots.config import BotConfig, PRICE_SCALE
from agentpit_bots.strategies.noise_trader import NoiseTrader
from agentpit_bots.strategies.base import MarketTokens


def _market():
    return MarketTokens(market_id=7, yes_token_id="yest", no_token_id="not")


_FULL_INV = {"yest": 10**15, "not": 10**15}


def test_returns_at_most_one_order_with_valid_shape():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(42))
    orders = strat.compute_desired_orders(
        market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
    )
    assert len(orders) == 1
    o = orders[0]
    assert o.side in {"BUY", "SELL"}
    assert o.token_id in {"yest", "not"}
    assert 0 < o.price_int < PRICE_SCALE  # within (0, 1) USD
    assert o.size > 0


def test_no_orders_when_mid_unknown():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []


def test_skips_sell_when_balance_below_size():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    orders = strat.compute_desired_orders(
        market=_market(), poly_yes_mid=0.5,
        token_balances={"yest": 0, "not": 0},
    )
    # First draw might be SELL (gets skipped → []) or BUY (placed). Either is
    # consistent with the contract — but if it IS a SELL, size > 0 means [].
    if orders:
        assert orders[0].side == "BUY"


def test_emits_sell_when_balance_meets_size():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    orders = strat.compute_desired_orders(
        market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
    )
    assert len(orders) == 1


def test_price_distance_respects_configured_bounds():
    """Over many ticks every sampled price lies within
    [anchor_mid ± noise_dist_min_usd, anchor_mid ± noise_dist_max_usd]."""
    cfg = BotConfig(noise_dist_min_usd=0.02, noise_dist_max_usd=0.20)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    distances: list[float] = []
    for _ in range(200):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
        )
        if not orders:
            continue
        o = orders[0]
        price = o.price_int / PRICE_SCALE
        # poly_yes_mid=0.5 so anchor_mid == 0.5 for both YES and NO outcomes.
        d = abs(price - 0.5)
        distances.append(d)
    assert distances, "expected at least one order over 200 ticks"
    eps = 1 / PRICE_SCALE  # rounding tolerance
    assert min(distances) >= 0.02 - eps
    assert max(distances) <= 0.20 + eps


def test_distance_sampling_spans_wider_than_anchor_spread():
    """Distinguishes the new distance-distribution from the old fixed-offset
    behavior — old strategy clamped at mm_half_spread_usd + 0.005."""
    cfg = BotConfig(noise_dist_max_usd=0.20, mm_half_spread_usd=0.005)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    max_d = 0.0
    for _ in range(500):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
        )
        if orders:
            d = abs(orders[0].price_int / PRICE_SCALE - 0.5)
            max_d = max(max_d, d)
    # Old behavior maxed at 0.01; new should regularly reach the 5+ cent range.
    assert max_d > 0.05


def test_distance_distribution_biased_toward_max():
    """Mean sampled distance lies in the upper half of [min, max] —
    the noise book should accumulate depth far from the spread, not near it."""
    cfg = BotConfig(noise_dist_min_usd=0.01, noise_dist_max_usd=0.20)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    samples: list[float] = []
    for _ in range(500):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
        )
        if orders:
            samples.append(abs(orders[0].price_int / PRICE_SCALE - 0.5))
    assert samples
    mean = sum(samples) / len(samples)
    midpoint = (0.01 + 0.20) / 2
    assert mean > midpoint, (
        f"mean distance {mean:.4f} should land in upper half of [0.01, 0.20] "
        f"(> {midpoint:.4f}); a left-biased distribution clusters too close to spread"
    )


def test_size_grows_with_distance_from_mid():
    """Per the spec: farther from mid → larger order. Compares the size of
    the smallest-distance sample to the size of the largest-distance sample."""
    cfg = BotConfig(
        noise_size_base_shares=5,
        noise_size_per_cent=10,
        noise_dist_min_usd=0.01,
        noise_dist_max_usd=0.30,
    )
    strat = NoiseTrader(cfg, rng=random.Random(0))
    pairs: list[tuple[float, int]] = []
    for _ in range(300):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.5, token_balances=_FULL_INV,
        )
        if orders:
            d = abs(orders[0].price_int / PRICE_SCALE - 0.5)
            pairs.append((d, orders[0].size))
    pairs.sort()
    nearest_d, nearest_size = pairs[0]
    farthest_d, farthest_size = pairs[-1]
    assert farthest_d > nearest_d
    assert farthest_size > nearest_size


def test_extreme_mid_does_not_emit_invalid_price():
    """When poly_yes_mid is near 0, BUYs would land below 0.01 after
    subtracting the sampled distance; the strategy must clip to [0.01, 0.99]."""
    cfg = BotConfig(noise_dist_min_usd=0.01, noise_dist_max_usd=0.30)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    for _ in range(200):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.01, token_balances=_FULL_INV,
        )
        if orders:
            assert 0.01 * PRICE_SCALE <= orders[0].price_int <= 0.99 * PRICE_SCALE
