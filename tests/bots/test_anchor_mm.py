"""AnchorMarketMaker.compute_desired_orders — pure function over (market, mid)."""

from agentpit_bots.config import BotConfig, PRICE_SCALE, SHARES_SCALE
from agentpit_bots.strategies.anchor_mm import AnchorMarketMaker, MarketTokens


def _market(yes_tok="yes-local", no_tok="no-local") -> MarketTokens:
    return MarketTokens(market_id=1, yes_token_id=yes_tok, no_token_id=no_tok)


def test_two_sided_quotes_around_midpoint():
    cfg = BotConfig(mm_half_spread_usd=0.01, mm_quote_size_shares=100)
    strat = AnchorMarketMaker(cfg)
    desired = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.50)
    by_key = {(d.side, d.token_id): d for d in desired}
    assert by_key[("BUY", "yes-local")].price_int == 490_000
    assert by_key[("SELL", "yes-local")].price_int == 510_000
    assert by_key[("BUY", "no-local")].price_int == 490_000
    assert by_key[("SELL", "no-local")].price_int == 510_000
    for d in desired:
        assert d.size == 100 * SHARES_SCALE


def test_mid_clipped_within_bounds():
    cfg = BotConfig(mm_half_spread_usd=0.05)
    strat = AnchorMarketMaker(cfg)
    desired = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.005)
    # YES bid would land at 0.005 - 0.05 = -0.045 → clipped to the 0.001 floor
    yes_buy = next(d for d in desired if d.side == "BUY" and d.token_id == "yes-local")
    assert yes_buy.price_int == 1_000  # $0.001 scaled


def test_quotes_snap_to_tenth_cent_tick():
    """Every quoted price lands on the 0.1¢ (0.001) grid — the order engine
    rejects finer precision, so the bot must quote on the tick (0.0075 ± 0.005
    would otherwise yield 0.0025 / 0.0125, off-grid)."""
    cfg = BotConfig(mm_half_spread_usd=0.005)
    strat = AnchorMarketMaker(cfg)
    desired = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.0075)
    assert desired
    for d in desired:
        assert d.price_int % 1000 == 0, f"{d.price_int} not on the 0.1¢ tick"


def test_no_quotes_when_mid_is_none():
    cfg = BotConfig()
    strat = AnchorMarketMaker(cfg)
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []


def test_skips_outcome_side_when_clipped_bid_meets_clipped_ask():
    """Self-cross guard: when clipping pushes bid >= ask, drop that side
    rather than post a guaranteed self-match. With the 0.001 floor this only
    happens for a sub-floor mid with a tiny spread."""
    # half=0.0004 + mid=0.0002 → YES bid/ask both clip to 0.001 (cross);
    # no_mid=0.9998 → no_bid=0.9994 > no_ask clip 0.999 (cross). Both skipped.
    cfg = BotConfig(mm_half_spread_usd=0.0004)
    strat = AnchorMarketMaker(cfg)
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=0.0002) == []


# --- active drift correction (sweep local price to the Polymarket target) ---


def _pi(p: float) -> int:
    return int(round(p * PRICE_SCALE))


def test_correction_sells_into_bids_above_target():
    """Local YES bids resting above the Polymarket target → the anchor places a
    SELL at the target to eat them down, sized to the volume above target+tol."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    # target YES = 0.10; bids resting at 0.30 (200) and 0.25 (100) — both above
    # 0.10 + 0.02 tol — plus one at 0.11 (50) inside tol (ignored).
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.10,
        yes_bids=[
            (_pi(0.30), 200 * SHARES_SCALE),
            (_pi(0.25), 100 * SHARES_SCALE),
            (_pi(0.11), 50 * SHARES_SCALE),
        ],
        yes_asks=[],
        no_bids=[],
        no_asks=[],
    )
    sells = [o for o in orders if o.token_id == "yes-local" and o.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].price_int == _pi(0.10)
    # Triggered by the 0.30/0.25 bids past tolerance, it then sweeps every bid
    # above the exact target (incl. the 0.11): 200 + 100 + 50.
    assert sells[0].size == 350 * SHARES_SCALE


def test_correction_buys_into_asks_below_target():
    """Local YES asks resting below target → BUY at target to lift them up."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.50,
        yes_bids=[],
        yes_asks=[(_pi(0.30), 120 * SHARES_SCALE), (_pi(0.49), 40 * SHARES_SCALE)],
        no_bids=[],
        no_asks=[],
    )
    buys = [o for o in orders if o.token_id == "yes-local" and o.side == "BUY"]
    assert len(buys) == 1
    assert buys[0].price_int == _pi(0.50)
    # Triggered by the 0.30 ask past tolerance, it lifts every ask below the
    # exact target (incl. the 0.49): 120 + 40.
    assert buys[0].size == 160 * SHARES_SCALE


def test_correction_noop_within_tolerance():
    """No corrective orders when the book sits within tolerance of the target."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.50,
        yes_bids=[(_pi(0.51), 100 * SHARES_SCALE)],  # within tol above
        yes_asks=[(_pi(0.49), 100 * SHARES_SCALE)],  # within tol below
        no_bids=[],
        no_asks=[],
    )
    assert orders == []


def test_correction_targets_no_token_at_one_minus_mid():
    """The NO outcome is corrected toward 1 - poly_yes_mid."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    # YES mid 0.10 → NO target 0.90. NO bids at 0.95 are above target → SELL NO.
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.10,
        yes_bids=[],
        yes_asks=[],
        no_bids=[(_pi(0.95), 80 * SHARES_SCALE)],
        no_asks=[],
    )
    no_sells = [o for o in orders if o.token_id == "no-local" and o.side == "SELL"]
    assert len(no_sells) == 1
    assert no_sells[0].price_int == _pi(0.90)
    assert no_sells[0].size == 80 * SHARES_SCALE


def test_correction_size_capped():
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=50)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.10,
        yes_bids=[(_pi(0.30), 999 * SHARES_SCALE)],
        yes_asks=[],
        no_bids=[],
        no_asks=[],
    )
    sell = next(o for o in orders if o.side == "SELL")
    assert sell.size == 50 * SHARES_SCALE  # capped


def test_correction_sweeps_when_best_ask_is_too_high():
    """The local mid can be dragged up by a too-high best ASK while bids rest at
    the floor (Congo DR: poly 0.0015, asks at 0.10+, bids at 0.01). The earlier
    logic only sold into over-high *bids*, so it produced nothing here and the
    market stayed drifted with corrections=0. The sweep must also act when the
    ask side sits above tolerance, selling down to the target."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.0015,
        yes_bids=[(_pi(0.01), 4300 * SHARES_SCALE)],  # within tol of target
        yes_asks=[(_pi(0.10), 95 * SHARES_SCALE), (_pi(0.15), 155 * SHARES_SCALE)],
        no_bids=[],
        no_asks=[],
    )
    sells = [o for o in orders if o.token_id == "yes-local" and o.side == "SELL"]
    assert len(sells) == 1
    # Target 0.0015 snaps to the 0.1¢ tick → 0.002 (round-half-to-even).
    assert sells[0].price_int == 2000
    assert sells[0].price_int % 1000 == 0


def test_correction_sweeps_when_best_bid_is_too_low():
    """Symmetric case: the mid is dragged down by a too-low best BID while asks
    sit near the ceiling. The sweep must BUY up to the target."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.95,
        yes_bids=[(_pi(0.50), 100 * SHARES_SCALE)],  # far below target 0.95
        yes_asks=[(_pi(0.99), 100 * SHARES_SCALE)],  # within tol of target
        no_bids=[],
        no_asks=[],
    )
    buys = [o for o in orders if o.token_id == "yes-local" and o.side == "BUY"]
    assert len(buys) == 1
    assert buys[0].price_int == _pi(0.95)


def test_correction_handles_extreme_target_below_quote_floor():
    """On a near-zero market (Tunisia: poly YES 0.002) the anchor's passive
    quote is skipped, but the sweep still sells inflated bids down to the true
    target — not the 0.01 quote floor — restoring YES≈poly and YES+NO≈1."""
    cfg = BotConfig(mm_correction_tolerance_usd=0.02, mm_correction_max_shares=10_000)
    strat = AnchorMarketMaker(cfg)
    orders = strat.compute_correction_orders(
        market=_market(),
        poly_yes_mid=0.002,
        yes_bids=[(_pi(0.29), 285 * SHARES_SCALE), (_pi(0.01), 4300 * SHARES_SCALE)],
        yes_asks=[],
        no_bids=[],
        no_asks=[],
    )
    sell = next(o for o in orders if o.token_id == "yes-local" and o.side == "SELL")
    assert sell.price_int == _pi(0.002)  # true target, below the 0.01 quote floor
