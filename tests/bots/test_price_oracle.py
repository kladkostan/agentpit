"""PriceOracle: batched + cached + tolerant of upstream failure."""
import pytest

from agentpit_bots.price_oracle import PriceOracle


class FakeClob:
    """Stand-in for py_clob_client.ClobClient."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.next_response: dict[str, float] = {}
        self.raise_next: bool = False

    def get_midpoints(self, params):
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError("polymarket down")
        token_ids = [p.token_id for p in params]
        self.calls.append(list(token_ids))
        return {tid: self.next_response.get(tid) for tid in token_ids}


@pytest.fixture
def fake_clob():
    return FakeClob()


def test_refresh_batches_into_one_call(fake_clob):
    fake_clob.next_response = {"t1": 0.42, "t2": 0.71}
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh(["t1", "t2"])
    assert snap.midpoint("t1") == 0.42
    assert snap.midpoint("t2") == 0.71
    assert fake_clob.calls == [["t1", "t2"]]


def test_midpoint_uses_cache_until_explicit_refresh(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh(["t1"])
    assert snap.midpoint("t1") == 0.5
    # change upstream — without refresh, snap still reads 0.5
    fake_clob.next_response = {"t1": 0.9}
    assert snap.midpoint("t1") == 0.5


def test_refresh_failure_keeps_previous_snapshot(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob)
    oracle.refresh(["t1"])
    fake_clob.raise_next = True
    snap = oracle.refresh(["t1"])   # second call raises; oracle swallows
    assert snap.midpoint("t1") == 0.5
    assert snap.is_stale("t1", stale_after_sec=10**9) is False  # within window


def test_is_stale_when_older_than_threshold(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob, now_fn=lambda: 1000)
    snap = oracle.refresh(["t1"])
    # snap was fetched at t=1000; later we ask with stale_after_sec=10 at t=1100
    assert snap.is_stale("t1", stale_after_sec=10, now=1100) is True
    assert snap.is_stale("t1", stale_after_sec=200, now=1100) is False


def test_midpoint_unknown_token_returns_none(fake_clob):
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh([])
    assert snap.midpoint("nope") is None
