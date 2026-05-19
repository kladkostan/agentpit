"""AnchorMarketMaker.compute_desired_orders — pure function over (market, mid)."""
from agentpit_bots.config import BotConfig, SHARES_SCALE
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
    # YES bid would land at 0.005 - 0.05 = -0.045 → clipped to 0.01
    yes_buy = next(d for d in desired if d.side == "BUY" and d.token_id == "yes-local")
    assert yes_buy.price_int == 10_000   # $0.01 scaled


def test_no_quotes_when_mid_is_none():
    cfg = BotConfig()
    strat = AnchorMarketMaker(cfg)
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []


def test_skips_outcome_side_when_clipped_bid_meets_clipped_ask():
    """Self-cross guard: when clipping pushes bid >= ask, drop that side
    rather than post a guaranteed self-match."""
    # half=0.005 + mid=0.001 → yes_bid clip to 0.01, yes_ask clip to 0.01 (cross).
    # no_mid=0.999 → no_bid=0.994, no_ask clip to 0.99 → cross.
    cfg = BotConfig(mm_half_spread_usd=0.005)
    strat = AnchorMarketMaker(cfg)
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=0.001) == []


