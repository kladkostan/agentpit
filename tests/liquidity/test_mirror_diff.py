# tests/liquidity/test_mirror_diff.py
from agentpit.liquidity.replica import MICRO, BookSnapshot
from agentpit.liquidity.reconciler import (
    LiveLevel, Placement, cap_sells_to_inventory, desired_levels, diff_levels,
    split_target_micro,
)

YES, NO = "tok-yes", "tok-no"


def _snap(bids=(), asks=()):
    return BookSnapshot(asset_id="pm-yes", bids=tuple(bids), asks=tuple(asks))


def test_desired_levels_yes_verbatim_no_complement():
    snap = _snap(bids=[(400_000, 10)], asks=[(600_000, 5)])
    got = set(desired_levels(snap, YES, NO))
    assert got == {
        Placement(YES, "BUY", 400_000, 10),     # YES bid verbatim
        Placement(NO, "SELL", 600_000, 10),     # its complement: SELL NO @ 1-0.40
        Placement(YES, "SELL", 600_000, 5),     # YES ask verbatim
        Placement(NO, "BUY", 400_000, 5),       # its complement: BUY NO @ 1-0.60
    }


def test_desired_levels_never_cross_within_either_token():
    # Non-crossed YES snapshot must yield non-crossed YES and NO books (spec §5).
    snap = _snap(bids=[(400_000, 1), (300_000, 2)], asks=[(410_000, 1), (900_000, 3)])
    desired = desired_levels(snap, YES, NO)
    for tok in (YES, NO):
        bids = [d.price_micro for d in desired if d.token_id == tok and d.side == "BUY"]
        asks = [d.price_micro for d in desired if d.token_id == tok and d.side == "SELL"]
        assert max(bids) < min(asks)


def test_diff_noop_when_book_already_mirrored():
    snap = _snap(bids=[(400_000, 10)], asks=[(600_000, 5)])
    current = [
        LiveLevel("o1", YES, "BUY", 400_000, 10),
        LiveLevel("o2", NO, "SELL", 600_000, 10),
        LiveLevel("o3", YES, "SELL", 600_000, 5),
        LiveLevel("o4", NO, "BUY", 400_000, 5),
    ]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert cancels == [] and places == []


def test_diff_size_change_is_cancel_plus_place():
    snap = _snap(bids=[(400_000, 7)], asks=())
    current = [LiveLevel("o1", YES, "BUY", 400_000, 10),
               LiveLevel("o2", NO, "SELL", 600_000, 10)]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert set(cancels) == {"o1", "o2"}
    assert set(places) == {Placement(YES, "BUY", 400_000, 7),
                           Placement(NO, "SELL", 600_000, 7)}


def test_diff_removed_level_cancelled_new_level_placed():
    snap = _snap(bids=[(410_000, 3)], asks=())
    current = [LiveLevel("o1", YES, "BUY", 400_000, 3),
               LiveLevel("o2", NO, "SELL", 600_000, 3)]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert set(cancels) == {"o1", "o2"}
    assert set(places) == {Placement(YES, "BUY", 410_000, 3),
                           Placement(NO, "SELL", 590_000, 3)}


def test_diff_duplicate_orders_at_one_level_keep_one_cancel_rest():
    # Crash mid-cycle can leave two orders at one level; keep one, cancel the dupe.
    snap = _snap(bids=[(400_000, 10)], asks=())
    current = [
        LiveLevel("o1", YES, "BUY", 400_000, 10),
        LiveLevel("o1b", YES, "BUY", 400_000, 10),
        LiveLevel("o2", NO, "SELL", 600_000, 10),
    ]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert cancels == ["o1b"] and places == []


def test_split_target_is_max_of_both_ask_sides():
    # YES asks need YES inventory; NO asks (= complement of YES bids) need NO.
    snap = _snap(bids=[(400_000, 70), (100_000, 30)], asks=[(600_000, 40)])
    assert split_target_micro(snap) == 100  # max(40, 70+30)


def test_cap_sells_keeps_best_prices_first():
    places = [
        Placement(YES, "SELL", 700_000, 6),
        Placement(YES, "SELL", 600_000, 5),   # best ask — must survive
        Placement(YES, "BUY", 400_000, 99),   # buys never capped
        Placement(NO, "SELL", 500_000, 4),
    ]
    got = cap_sells_to_inventory(places, {YES: 8, NO: 0})
    assert Placement(YES, "SELL", 600_000, 5) in got
    assert Placement(YES, "SELL", 700_000, 6) not in got   # inventory exhausted (8 < 5+6)
    assert Placement(NO, "SELL", 500_000, 4) not in got    # zero NO inventory
    assert Placement(YES, "BUY", 400_000, 99) in got
