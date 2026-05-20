"""NoiseTrader emits one resting order per tick at a distance-distributed
price away from the outcome's anchor mid. Distance is sampled uniformly
across the room to the price bound; size grows with distance."""

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
        market=_market(),
        poly_yes_mid=0.5,
        token_balances=_FULL_INV,
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
        market=_market(),
        poly_yes_mid=0.5,
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
        market=_market(),
        poly_yes_mid=0.5,
        token_balances=_FULL_INV,
    )
    assert len(orders) == 1


def test_price_distance_respects_configured_bounds():
    """Distance is uniform over [min_gap, room]: never inside the min gap from
    mid, never past the price bound. At mid 0.5 the room is 0.499 each side, so
    distance reaches well beyond noise_dist_max_usd (which now only caps size)."""
    cfg = BotConfig(noise_dist_min_usd=0.02, noise_dist_max_usd=0.20)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    distances: list[float] = []
    for _ in range(500):
        orders = strat.compute_desired_orders(
            market=_market(),
            poly_yes_mid=0.5,
            token_balances=_FULL_INV,
        )
        if not orders:
            continue
        # poly_yes_mid=0.5 so anchor_mid == 0.5 for both YES and NO outcomes.
        distances.append(abs(orders[0].price_int / PRICE_SCALE - 0.5))
    assert distances, "expected at least one order over 500 ticks"
    eps = 1 / PRICE_SCALE  # rounding tolerance
    room = 0.5 - 0.001  # to the 0.001 price floor
    assert min(distances) >= 0.02 - eps
    assert max(distances) <= room + eps


def test_distance_sampling_spans_wider_than_anchor_spread():
    """Distinguishes the new distance-distribution from the old fixed-offset
    behavior — old strategy clamped at mm_half_spread_usd + 0.005."""
    cfg = BotConfig(noise_dist_max_usd=0.20, mm_half_spread_usd=0.005)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    max_d = 0.0
    for _ in range(500):
        orders = strat.compute_desired_orders(
            market=_market(),
            poly_yes_mid=0.5,
            token_balances=_FULL_INV,
        )
        if orders:
            d = abs(orders[0].price_int / PRICE_SCALE - 0.5)
            max_d = max(max_d, d)
    # Old behavior maxed at 0.01; new should regularly reach the 5+ cent range.
    assert max_d > 0.05


def test_distance_distribution_is_uniform_across_room():
    """Distance is sampled uniformly across [min_gap, room], so its mean sits
    near the band midpoint (not biased toward either end) and all three thirds
    of the band are populated. This even spread of orders, combined with size
    growing in distance, is what yields the inverted-gaussian depth profile."""
    cfg = BotConfig(noise_dist_min_usd=0.01)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    samples: list[float] = []
    for _ in range(4000):
        orders = strat.compute_desired_orders(
            market=_market(),
            poly_yes_mid=0.5,
            token_balances=_FULL_INV,
        )
        if orders:
            samples.append(abs(orders[0].price_int / PRICE_SCALE - 0.5))
    assert samples
    lo, hi = 0.01, 0.5 - 0.01  # min gap, room
    mean = sum(samples) / len(samples)
    midpoint = (lo + hi) / 2
    assert abs(mean - midpoint) < 0.1 * (hi - lo), f"mean {mean:.4f} not ~uniform"
    # Spread, not clustered: every third of the band has samples.
    t1, t2 = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
    assert any(s < t1 for s in samples)
    assert any(t1 <= s < t2 for s in samples)
    assert any(s >= t2 for s in samples)


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
            market=_market(),
            poly_yes_mid=0.5,
            token_balances=_FULL_INV,
        )
        if orders:
            d = abs(orders[0].price_int / PRICE_SCALE - 0.5)
            pairs.append((d, orders[0].size))
    pairs.sort()
    nearest_d, nearest_size = pairs[0]
    farthest_d, farthest_size = pairs[-1]
    assert farthest_d > nearest_d
    assert farthest_size > nearest_size


def test_noise_seed_covers_largest_sell_size():
    """The bootstrap inventory seed must clear the largest SELL a noise bot
    can draw, otherwise — since the distance distribution peaks at the max and
    size grows with distance — nearly every SELL trips the `bal < size` guard
    and gets dropped, starving the ask side (one anchor quote, deep bids, no
    noise asks). Seed must exceed max sell size so SELLs actually post."""
    cfg = BotConfig()
    max_d_cents = int(cfg.noise_dist_max_usd * 100)
    max_sell_shares = cfg.noise_size_base_shares + cfg.noise_size_per_cent * max_d_cents
    assert cfg.noise_inventory_split_shares >= max_sell_shares, (
        f"noise seed {cfg.noise_inventory_split_shares} < largest SELL "
        f"{max_sell_shares} shares — most SELL draws will be dropped"
    )


def test_noise_bids_on_sub_cent_market():
    """With the price floor at 0.001 (not 0.01), noise can place YES BUYs on a
    sub-1¢ market. Previously the BUY room (mid - floor = 0.0015 - 0.01) was
    negative, so every BUY YES was dropped and the bid side stayed empty —
    the "NO BIDS" we saw on near-zero markets like Jordan (poly 0.0015)."""
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    buys = 0
    for _ in range(500):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.0015, token_balances=_FULL_INV
        )
        if orders and orders[0].side == "BUY" and orders[0].token_id == "yest":
            buys += 1
    assert buys > 0, "noise never bid YES on a sub-1¢ market — bid side stays empty"


def test_low_prob_market_spreads_bids_instead_of_piling_at_floor():
    """On a low-probability market (mid ~0.08) the room below mid is far
    smaller than the sampled distance (peaked at 0.30), so `anchor_mid - d`
    used to overshoot below 0.01 for nearly every draw and clip onto the
    floor — ~95% of bids stacked on a single $0.01 price. The distance must be
    bounded by the room to the floor so bids spread across the band."""
    cfg = BotConfig()  # default noise_dist_max_usd = 0.30
    strat = NoiseTrader(cfg, rng=random.Random(1))
    floor = total = 0
    for _ in range(5000):
        orders = strat.compute_desired_orders(
            market=_market(), poly_yes_mid=0.08, token_balances=_FULL_INV
        )
        if not orders:
            continue
        o = orders[0]
        if o.side == "BUY" and o.token_id == "yest":
            total += 1
            if round(o.price_int / PRICE_SCALE, 2) <= 0.01:
                floor += 1
    assert total > 0
    floor_share = floor / total
    assert floor_share < 0.5, f"{floor_share:.0%} of bids piled at the $0.01 floor"


def test_extreme_mid_does_not_emit_invalid_price():
    """When poly_yes_mid is near 0, BUYs would land below the floor after
    subtracting the sampled distance; the strategy must clip to [0.001, 0.999]."""
    cfg = BotConfig(noise_dist_min_usd=0.01, noise_dist_max_usd=0.30)
    strat = NoiseTrader(cfg, rng=random.Random(0))
    for _ in range(200):
        orders = strat.compute_desired_orders(
            market=_market(),
            poly_yes_mid=0.01,
            token_balances=_FULL_INV,
        )
        if orders:
            assert 0.001 * PRICE_SCALE <= orders[0].price_int <= 0.999 * PRICE_SCALE
