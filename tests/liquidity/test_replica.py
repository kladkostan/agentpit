from agentpit.liquidity.replica import MICRO, TICK, BookReplica, to_micro


def _book_msg(asset="A", bids=None, asks=None):
    return {
        "event_type": "book", "asset_id": asset,
        "bids": [{"price": p, "size": s} for p, s in (bids or [])],
        "asks": [{"price": p, "size": s} for p, s in (asks or [])],
    }


def test_to_micro_decimal_strings_never_float():
    assert to_micro("0.48") == 480_000
    assert to_micro(".5") == 500_000          # Polymarket emits ".48"-style strings
    assert to_micro("0.980") == 980_000       # trailing-zero variant
    assert to_micro("145369.13") == 145_369_130_000
    assert to_micro("garbage") is None
    assert to_micro(None) is None


def test_apply_book_replaces_state_and_seeds():
    r = BookReplica("A")
    assert r.snapshot() is None               # unseeded → unusable
    assert r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert r.apply_book(_book_msg(bids=[("0.45", "7")], asks=[("0.55", "3")]))
    snap = r.snapshot()
    assert snap.bids == ((450_000, 7_000_000),)   # fully replaced, not merged
    assert snap.asks == ((550_000, 3_000_000),)


def test_apply_book_wrong_asset_rejected():
    r = BookReplica("A")
    assert not r.apply_book(_book_msg(asset="B", bids=[("0.4", "1")]))
    assert r.snapshot() is None


def test_apply_book_skips_off_tick_zero_and_garbage_levels():
    r = BookReplica("A")
    r.apply_book(_book_msg(
        bids=[("0.4005", "10"), ("0.40", "0"), ("x", "1"), ("0.41", "2")],
        asks=[("0.60", "1")]))
    snap = r.snapshot()
    assert snap.bids == ((410_000, 2_000_000),)   # off-tick, zero-size, garbage dropped


def test_snapshot_orders_best_first_regardless_of_input_order():
    # Live feed sends arrays worst-to-best; never trust array order.
    r = BookReplica("A")
    r.apply_book(_book_msg(
        bids=[("0.10", "1"), ("0.40", "2")],     # ascending (worst first)
        asks=[("0.90", "1"), ("0.60", "2")]))    # descending (worst first)
    snap = r.snapshot()
    assert snap.bids[0] == (400_000, 2_000_000)  # best bid first
    assert snap.asks[0] == (600_000, 2_000_000)  # best (lowest) ask first


def test_price_change_replace_semantics_and_delete():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})
    assert r.snapshot().bids == ((400_000, 3_000_000),)   # replace, not add
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "0"})
    assert r.snapshot().bids == ()                        # size 0 = level removed
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "SELL", "price": "0.61", "size": "2"})
    assert r.snapshot().asks == ((600_000, 5_000_000), (610_000, 2_000_000))


def test_price_change_sibling_asset_filtered():
    # price_change messages carry mirrored entries for BOTH sibling asset_ids.
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert not r.apply_price_change_entry(
        {"asset_id": "SIBLING", "side": "SELL", "price": "0.60", "size": "9"})
    assert r.snapshot().bids == ((400_000, 10_000_000),)


def test_price_change_before_seed_ignored():
    r = BookReplica("A")
    assert not r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})


def test_tick_size_change_resets_epoch_until_fresh_snapshot():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    r.mark_stale()                                        # tick_size_change / watchdog
    assert r.snapshot() is None
    assert not r.apply_price_change_entry(                # deltas dropped while stale
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})
    r.apply_book(_book_msg(bids=[("0.30", "1")], asks=[("0.70", "1")]))
    assert r.snapshot().bids == ((300_000, 1_000_000),)   # fresh snapshot re-seeds


def test_crossed_replica_yields_no_snapshot():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.60", "1")], asks=[("0.55", "1")]))
    assert r.snapshot() is None


def test_one_sided_and_empty_books_are_valid():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "1")], asks=[]))
    snap = r.snapshot()
    assert snap.bids == ((400_000, 1_000_000),) and snap.asks == ()


def test_to_micro_rejects_non_finite_and_overflow():
    assert to_micro("Infinity") is None
    assert to_micro("inf") is None
    assert to_micro("-Infinity") is None
    assert to_micro("NaN") is None
    assert to_micro("1e1000") is None


def test_apply_book_with_infinity_level_does_not_corrupt_other_side():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    r.apply_book(_book_msg(bids=[("0.45", "7")], asks=[("Infinity", "1")]))
    snap = r.snapshot()
    assert snap.asks == ()                       # bad level dropped, not stale-retained
    assert snap.bids == ((450_000, 7_000_000),)  # and no exception escaped


def test_sizes_snapped_down_to_milli_share_grid():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10.1234567"), ("0.30", "0.0009")],
                           asks=[("0.60", "5")]))
    snap = r.snapshot()
    assert snap.bids == ((400_000, 10_123_000),)   # snapped down; dust level dropped
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "SELL", "price": "0.61", "size": "2.0006"})
    assert dict(r.snapshot().asks)[610_000] == 2_000_000
