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
    # than one full interval for its first deep reconcile.
    now, interval = 5_000.0, 1800.0
    seed = cold_seed("asset-42", interval, now)
    assert cold_due(seed, interval, now + interval) is True


def test_cold_seed_is_within_one_interval_in_the_past():
    now, interval = 10_000.0, 1800.0
    for asset in ("a", "b", "c", "d", "e"):
        seed = cold_seed(asset, interval, now)
        assert now - interval <= seed <= now


def test_cold_seed_is_stable_across_calls():
    # Must not use Python's salted hash(): a restart would reshuffle every
    # market's due time and could bunch them together.
    assert cold_seed("market-7", 1800.0, 500.0) == cold_seed("market-7", 1800.0, 500.0)


def test_cold_seed_spreads_assets_across_the_interval():
    # 200 assets should not land in one bucket: with 10 buckets over the
    # interval, every bucket gets at least one asset.
    now, interval = 0.0, 1000.0
    buckets = {int((now - cold_seed(f"asset-{i}", interval, now)) // 100) for i in range(200)}
    assert len(buckets) == 10


def test_cold_seed_handles_a_sub_second_interval():
    # `% int(interval)` raised ZeroDivisionError for interval < 1 — the
    # fractional offset must stay well-defined and within one interval.
    now, interval = 10_000.0, 0.5
    for asset in ("a", "b", "c", "d", "e"):
        seed = cold_seed(asset, interval, now)
        assert now - interval <= seed <= now


def test_cold_seed_still_spreads_assets_when_interval_is_just_above_one():
    # `% int(interval)` collapsed every offset to a constant 0 for any
    # interval in [1, 2), defeating the stagger entirely.
    now, interval = 10_000.0, 1.5
    seeds = {cold_seed(f"asset-{i}", interval, now) for i in range(50)}
    assert len(seeds) > 1
