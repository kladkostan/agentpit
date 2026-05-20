"""reconcile(live, desired) → (cancels, creates)

Two orders are considered equivalent when same (side, token_id, price_int, size).
Anything live that isn't matched gets cancelled. Anything desired not matched
gets created. The size match is exact — partial fills aren't treated as a match.
"""

from agentpit_bots.reconcile import DesiredOrder, LiveOrder, reconcile


def _live(order_id, side, token_id, price_int, size):
    return LiveOrder(
        order_id=order_id,
        side=side,
        token_id=token_id,
        price_int=price_int,
        remaining_amount=size,
    )


def _desired(side, token_id, price_int, size):
    return DesiredOrder(
        side=side,
        token_id=token_id,
        price_int=price_int,
        size=size,
    )


def test_empty_in_empty_out():
    cancels, creates = reconcile([], [])
    assert cancels == []
    assert creates == []


def test_all_desired_when_none_live():
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile([], desired)
    assert cancels == []
    assert creates == desired


def test_all_cancelled_when_none_desired():
    live = [_live("o1", "BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, [])
    assert cancels == ["o1"]
    assert creates == []


def test_exact_match_no_action():
    live = [_live("o1", "BUY", "t1", 500000, 100)]
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == []
    assert creates == []


def test_price_changed_cancels_and_recreates():
    live = [_live("o1", "BUY", "t1", 490000, 100)]
    desired = [_desired("BUY", "t1", 510000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == ["o1"]
    assert creates == desired


def test_partial_fill_counts_as_mismatch_and_recreates():
    live = [_live("o1", "BUY", "t1", 500000, 60)]  # was 100, 40 filled
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == ["o1"]
    assert creates == desired


def test_multi_outcome_independent():
    live = [
        _live("o1", "BUY", "yes_tok", 500000, 100),  # keep
        _live("o2", "SELL", "yes_tok", 600000, 100),  # cancel (not desired)
        _live("o3", "BUY", "no_tok", 400000, 100),  # keep
    ]
    desired = [
        _desired("BUY", "yes_tok", 500000, 100),
        _desired("BUY", "no_tok", 400000, 100),
        _desired("SELL", "yes_tok", 510000, 100),  # new — wasn't live
    ]
    cancels, creates = reconcile(live, desired)
    assert set(cancels) == {"o2"}
    assert creates == [_desired("SELL", "yes_tok", 510000, 100)]
