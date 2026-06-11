"""The /events listing has a short-TTL response cache so a high client poll
rate collapses to ~one DB read per TTL window."""

import agentpit.api.routes.events as events
from agentpit.api.routes.events import _EVENTS_TTL_S, _list_events_cached


class _FakeService:
    """Counts DB reads; returns a page tagged with the call number."""

    def __init__(self) -> None:
        self.calls = 0

    def list_events_gamma(self, *, limit: int, offset: int):
        self.calls += 1
        return [f"page-{limit}-{offset}-call{self.calls}"]


def setup_function() -> None:
    events._events_cache.clear()


def test_hit_within_ttl_skips_the_db():
    svc = _FakeService()
    first = _list_events_cached(svc, limit=20, offset=0, now=100.0)
    again = _list_events_cached(
        svc, limit=20, offset=0, now=100.0 + _EVENTS_TTL_S - 0.001
    )
    assert svc.calls == 1  # second read served from cache
    assert again == first


def test_refetches_after_ttl_expires():
    svc = _FakeService()
    _list_events_cached(svc, limit=20, offset=0, now=100.0)
    _list_events_cached(svc, limit=20, offset=0, now=100.0 + _EVENTS_TTL_S + 0.001)
    assert svc.calls == 2  # expired -> fresh DB read


def test_distinct_pages_cache_independently():
    svc = _FakeService()
    _list_events_cached(svc, limit=20, offset=0, now=100.0)
    _list_events_cached(svc, limit=20, offset=20, now=100.0)  # next page
    assert svc.calls == 2  # different (limit, offset) -> separate entries
