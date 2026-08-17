# tests/liquidity/test_mirror_cold.py
from agentpit.liquidity.mirror import cold_due, cold_seed


def test_cold_due_only_after_a_full_interval():
    assert cold_due(last_cold=1000.0, interval=1800.0, now=2799.0) is False
    assert cold_due(last_cold=1000.0, interval=1800.0, now=2800.0) is True
    assert cold_due(last_cold=1000.0, interval=1800.0, now=9999.0) is True


def test_cold_due_never_when_sweeps_are_disabled():
    # interval <= 0 turns the cold tier off entirely: every pass stays hot.
    assert cold_due(last_cold=0.0, interval=0.0, now=1e9) is False
    assert cold_due(last_cold=0.0, interval=-1.0, now=1e9) is False


def test_a_seeded_asset_is_due_within_one_interval():
    # The seed offsets the first sweep into the past, so no market waits longer
    # than one full interval for its first deep reconcile — whatever its place
    # in the queue.
    now, interval = 5_000.0, 1800.0
    for priority in (0.0, 0.25, 0.5, 1.0):
        seed = cold_seed(priority, interval, now)
        assert cold_due(seed, interval, now + interval) is True


def test_the_busiest_market_sweeps_first_and_the_quietest_last():
    # The reason this takes a priority at all: the mirror ranks markets by 24h
    # volume, and the top of that ranking must not wait behind the tail.
    now, interval = 10_000.0, 1800.0
    assert cold_due(cold_seed(1.0, interval, now), interval, now) is True
    assert cold_due(cold_seed(0.0, interval, now), interval, now) is False
    assert cold_due(cold_seed(0.0, interval, now), interval, now + interval) is True


def test_cold_seed_is_within_one_interval_in_the_past():
    now, interval = 10_000.0, 1800.0
    for priority in (0.0, 0.1, 0.5, 0.9, 1.0):
        seed = cold_seed(priority, interval, now)
        assert now - interval <= seed <= now


def test_a_priority_outside_the_unit_range_is_clamped():
    # Ranking arithmetic upstream should not be able to push a market beyond
    # the interval in either direction: a seed further back than one interval
    # would fire immediately forever, one in the future would never fire.
    now, interval = 10_000.0, 1800.0
    assert cold_seed(5.0, interval, now) == cold_seed(1.0, interval, now)
    assert cold_seed(-5.0, interval, now) == cold_seed(0.0, interval, now)


def test_cold_seed_is_stable_across_calls():
    # A restart must not reshuffle due times and bunch markets together; with
    # the ranking upstream, equal priority means equal slot.
    assert cold_seed(0.3, 1800.0, 500.0) == cold_seed(0.3, 1800.0, 500.0)


def test_a_range_of_priorities_spreads_across_the_interval():
    # 200 markets ranked evenly should not land in one bucket: with 10 buckets
    # over the interval, every bucket gets at least one.
    now, interval = 0.0, 1000.0
    buckets = {
        int((now - cold_seed(1.0 - i / 200, interval, now)) // 100)
        for i in range(200)
    }
    # Every tenth of the interval is occupied. Stated as coverage rather than
    # a count: priority 1.0 lands exactly on the boundary and floors into an
    # eleventh bucket of its own, which is correct and says nothing about the
    # spread this test is about.
    assert set(range(10)) <= buckets


def test_cold_seed_handles_a_sub_second_interval():
    # `% int(interval)` raised ZeroDivisionError for interval < 1 — the
    # fractional offset must stay well-defined and within one interval.
    now, interval = 10_000.0, 0.5
    for priority in (0.0, 0.5, 1.0):
        seed = cold_seed(priority, interval, now)
        assert now - interval <= seed <= now


def test_cold_seed_still_spreads_when_interval_is_just_above_one():
    # `% int(interval)` collapsed every offset to a constant 0 for any
    # interval in [1, 2), defeating the stagger entirely.
    now, interval = 10_000.0, 1.5
    seeds = {cold_seed(i / 50, interval, now) for i in range(50)}
    assert len(seeds) > 1
