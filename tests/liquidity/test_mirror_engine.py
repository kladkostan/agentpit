# tests/liquidity/test_mirror_engine.py
import asyncio

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
    monkeypatch.setattr(mirror, "_load_refs", lambda db: refs_box["refs"])
    eng = MirrorEngine.__new__(MirrorEngine)   # skip __init__ deps (db/onchain)
    eng._db = None
    eng._cfg = None
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
