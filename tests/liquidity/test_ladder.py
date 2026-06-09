import pytest

from agentpit.liquidity.ladder import MICRO, TICK, build_ladder


def _build(mid=500_000, **kw):
    kw.setdefault("rungs_per_side", 8)
    kw.setdefault("wall_fraction", 0.6)
    kw.setdefault("size_per_side_micro", 10_000 * MICRO)
    return build_ladder(mid, **kw)


def test_count_and_sides():
    rungs = _build()
    bids = [r for r in rungs if r.side == "BUY"]
    asks = [r for r in rungs if r.side == "SELL"]
    assert len(bids) == 8 and len(asks) == 8


def test_strictly_non_crossing():
    mid = 500_000
    rungs = _build(mid=mid)
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert max(bids) < mid < min(asks)
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


def test_respects_existing_touch():
    rungs = build_ladder(
        500_000, rungs_per_side=4, wall_fraction=0.5,
        size_per_side_micro=MICRO, best_ask_micro=490_000, best_bid_micro=480_000,
    )
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert max(bids) < 490_000
    assert min(asks) > 480_000


@pytest.mark.parametrize("mid", [10_000, 50_000, 500_000, 950_000, 990_000])
def test_non_crossing_at_all_mids(mid):
    rungs = build_ladder(
        mid, rungs_per_side=8, wall_fraction=0.6, size_per_side_micro=10_000 * MICRO
    )
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert all(0 < p < MICRO and p % TICK == 0 for p in bids + asks)
    assert max(bids) < mid < min(asks)
    assert max(bids) < min(asks)
    # wall is the outermost rung and must stay on the correct side of mid
    assert min(bids) < mid and max(asks) > mid
