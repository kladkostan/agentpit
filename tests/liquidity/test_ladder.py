import pytest

from agentpit.liquidity.ladder import MICRO, TICK, build_ladder


def _build(bid=499_000, ask=501_000, **kw):
    kw.setdefault("rungs_per_side", 8)
    kw.setdefault("wall_fraction", 0.6)
    kw.setdefault("size_per_side_micro", 10_000 * MICRO)
    return build_ladder(bid, ask, **kw)


def test_count_and_sides():
    rungs = _build()
    bids = [r for r in rungs if r.side == "BUY"]
    asks = [r for r in rungs if r.side == "SELL"]
    assert len(bids) == 8 and len(asks) == 8


def test_strictly_non_crossing():
    bid_anchor = 499_000
    ask_anchor = 501_000
    rungs = _build(bid=bid_anchor, ask=ask_anchor)
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert max(bids) <= bid_anchor < ask_anchor <= min(asks)
    assert max(bids) < min(asks)


def test_prices_on_tick_and_in_bounds():
    for r in _build():
        assert 0 < r.price_micro < MICRO
        assert r.price_micro % TICK == 0


def test_wall_carries_wall_fraction_of_size():
    size = 10_000 * MICRO
    rungs = _build(size_per_side_micro=size, wall_fraction=0.6)
    bids = [r for r in rungs if r.side == "BUY"]
    wall = min(bids, key=lambda r: r.price_micro)
    assert abs(wall.size_micro - round(0.6 * size)) <= TICK


@pytest.mark.parametrize("bid_anchor,ask_anchor", [
    (2_000, 4_000),
    (50_000, 60_000),
    (490_000, 510_000),
    (940_000, 960_000),
    (996_000, 998_000),
])
def test_non_crossing_at_all_anchors(bid_anchor, ask_anchor):
    rungs = build_ladder(
        bid_anchor, ask_anchor,
        rungs_per_side=8, wall_fraction=0.6, size_per_side_micro=10_000 * MICRO
    )
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert all(0 < p < MICRO and p % TICK == 0 for p in bids + asks)
    assert max(bids) < min(asks)
    # wall is the outermost rung and must stay on the correct side of the anchor
    assert min(bids) < bid_anchor
    assert max(asks) > ask_anchor
