# tests/liquidity/test_mirror_engine.py
import asyncio
from types import SimpleNamespace

import pytest

from agentpit.liquidity import mirror
from agentpit.liquidity.feed import MarketRef
from agentpit.liquidity.mirror import MirrorEngine


def _ref(i, pm):
    return MarketRef(market_id=i, condition_id=f"0xc{i}", yes_token=f"y{i}",
                     no_token=f"n{i}", pm_yes_token=pm)


class FlakyOrders:
    """cancel_market_orders raises N times, then succeeds."""
    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    def cancel_market_orders(self, user, market, asset_id):
        self.calls.append(market)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("transient cancel failure")


def _engine(monkeypatch, refs_box, orders):
    monkeypatch.setattr(
        mirror, "_load_refs", lambda db, cats=None, tags=None: refs_box["refs"]
    )
    eng = MirrorEngine.__new__(MirrorEngine)   # skip __init__ deps (db/onchain)
    eng._db = None
    # Only the fields `_refresh_targets` actually reads; the engine is built
    # by __new__ precisely to keep the real Settings/db/chain out of the test.
    eng._cfg = SimpleNamespace(excluded_categories=[], excluded_tags=[])
    eng._user = None
    eng._order = orders
    from agentpit.liquidity.feed import MirrorState
    eng.state = MirrorState([])
    eng._resubscribe = asyncio.Event()
    eng._pending_cancel = []
    return eng


async def test_refresh_signals_resubscribe_even_when_cancel_raises(monkeypatch):
    a, b = _ref(1, "PM-A"), _ref(2, "PM-B")
    refs_box = {"refs": [a, b]}
    orders = FlakyOrders(failures=1)
    eng = _engine(monkeypatch, refs_box, orders)

    await eng._refresh_targets()               # adds A+B
    assert eng._resubscribe.is_set()
    eng._resubscribe.clear()

    refs_box["refs"] = [b]                     # A removed; its cancel will RAISE
    await eng._refresh_targets()
    assert eng._resubscribe.is_set(), "signal must fire despite the failed cancel"
    assert orders.calls == ["0xc1"]            # attempted once

    refs_box["refs"] = [b]                     # no target change on next refresh
    eng._resubscribe.clear()
    await eng._refresh_targets()
    assert orders.calls == ["0xc1", "0xc1"], "failed cancel must be retried"
    assert not eng._pending_cancel, "retry succeeded — pending list drained"
    assert not eng._resubscribe.is_set()       # no change ⇒ no spurious rebuild


async def test_drain_tape_validates_price_range_and_caps(monkeypatch):
    a = _ref(1, "PM-A")
    refs_box = {"refs": [a]}
    eng = _engine(monkeypatch, refs_box, FlakyOrders(failures=0))
    await eng._refresh_targets()

    class Cfg:
        mirror_tape_enabled = True
    eng._cfg = Cfg()

    written = []
    monkeypatch.setattr(mirror.tape, "insert_mirrored_trade",
                        lambda conn, **kw: written.append(kw))

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *args): return False

    class FakeDb:
        def write(self): return FakeConn()
    eng._db = FakeDb()

    def ev(price, size="10", side="BUY", ts="1700000000000"):
        return {"event_type": "last_trade_price", "asset_id": "PM-A",
                "price": price, "size": size, "side": side, "timestamp": ts}

    eng.state.trades.extend([ev("-0.5"), ev("1.5"), ev("0"), ev("0.48")])
    await eng._drain_tape()
    assert len(written) == 1 and written[0]["price_micro"] == 480_000

    eng.state.trades.extend(ev("0.5") for _ in range(250))
    await eng._drain_tape()
    assert len(written) == 1 + 200, "drain capped at 200/cycle"
    assert len(eng.state.trades) == 50, "remainder stays queued for next cycle"


# ---- _ref_of + fill_markets (sync->fill coupling) -------------------------


class _Cond:
    value = "0xcond7"


def test_ref_of_filters_and_builds():
    from agentpit.liquidity.mirror import _ref_of

    assert _ref_of(None) is None

    class _NoToken:
        polymarket_yes_token_id = None
        erc1155_tokens = [("y", "Up"), ("n", "Down")]

    assert _ref_of(_NoToken()) is None  # no upstream token -> not mirrorable

    class _NotBinary:
        polymarket_yes_token_id = "PM"
        erc1155_tokens = [("y", "Up")]

    assert _ref_of(_NotBinary()) is None

    class _Ok:
        market_id = 7
        polymarket_yes_token_id = "PM7"
        erc1155_tokens = [("y7", "Up"), ("n7", "Down")]
        condition_id = _Cond()

    r = _ref_of(_Ok())
    assert (r.market_id, r.pm_yes_token, r.yes_token, r.no_token, r.condition_id) == (
        7,
        "PM7",
        "y7",
        "n7",
        "0xcond7",
    )


class _ReadDb:
    def read(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield "CONN"

        return _cm()


async def test_fill_markets_empty_is_noop():
    eng = MirrorEngine.__new__(MirrorEngine)
    assert await eng.fill_markets([]) == 0


async def test_fill_markets_seeds_then_reconciles(monkeypatch):
    eng = MirrorEngine.__new__(MirrorEngine)
    eng._db = _ReadDb()
    eng._order = object()
    eng._onchain = object()
    eng._user = object()
    eng._cfg = object()

    ref = _ref(7, "PM7")
    monkeypatch.setattr(mirror, "_ref_of", lambda m: ref)
    monkeypatch.setattr(mirror.TableRead, "read_market", lambda conn, mid: "MARKET")
    monkeypatch.setattr(
        mirror.feed,
        "fetch_books_rest",
        lambda assets: [{"asset_id": "PM7", "bids": [], "asks": []}],
    )

    class _Rep:
        def __init__(self, asset):
            pass

        def apply_book(self, ev):
            return True

        def snapshot(self):
            return "SNAP"

    monkeypatch.setattr(mirror, "BookReplica", _Rep)

    seen = {}

    def fake_reconcile(db, order, onchain, user, r, snap, cfg):
        seen["ref"] = r
        seen["snap"] = snap
        return {"placed": 5, "cancelled": 0}

    monkeypatch.setattr(mirror, "reconcile_market", fake_reconcile)

    placed = await eng.fill_markets([7])
    assert placed == 5
    assert seen["ref"] is ref and seen["snap"] == "SNAP"
