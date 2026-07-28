import time

from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.event_with_markets import ListEventCategoriesResponse
from agentpit.datastructures.gamma_market import GammaEvent

router = APIRouter(tags=["events"])

# Short-TTL response cache for the event listing. The home page polls /events
# every few seconds; without a cache, N clients = N DB reads per interval even
# though the list only changes when a sync runs. With it, a poll burst collapses
# to ~one DB read per TTL window, regardless of client count. Keyed by
# (limit, offset, category) — the category MUST be part of the key or a
# filtered page would be served to an unfiltered request (and vice versa) for
# up to one TTL. Per-process; staleness is bounded by the TTL.
_EVENTS_TTL_S = 3.0
_events_cache: dict[tuple[int, int, str | None], tuple[float, list[GammaEvent]]] = {}


def _list_events_cached(
    service, *, limit: int, offset: int, category: str | None = None, now: float
) -> list[GammaEvent]:
    """Return the cached page if it is younger than the TTL, else fetch + store.

    `now` is injected (monotonic seconds) so the TTL is deterministically
    testable. The sync `def` route runs in FastAPI's threadpool; dict get/set
    are atomic in CPython, so no lock is needed — a rare concurrent miss just
    does one extra harmless DB read.
    """
    # Normalise first so `?category=` and no param share one cache entry.
    normalized = category.strip() if category else None
    key = (limit, offset, normalized or None)
    hit = _events_cache.get(key)
    if hit is not None and now - hit[0] < _EVENTS_TTL_S:
        return hit[1]
    result = service.list_events_gamma(limit=limit, offset=offset, category=normalized)
    _events_cache[key] = (now, result)
    return result


@router.get("/events", response_model=list[GammaEvent])
def list_events(
    service: EventServiceDep,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
) -> list[GammaEvent]:
    return _list_events_cached(
        service,
        limit=limit,
        offset=offset,
        category=category,
        now=time.monotonic(),
    )


# NOTE: declaration order is load-bearing. FastAPI matches routes in the order
# they are registered, so /events/categories MUST stay above /events/{slug} —
# otherwise it resolves as get_event(slug="categories") and 404s.
@router.get("/events/categories", response_model=ListEventCategoriesResponse)
def list_event_categories(service: EventServiceDep) -> ListEventCategoriesResponse:
    return service.list_categories()


@router.get("/events/{slug}", response_model=GammaEvent)
def get_event(slug: str, service: EventServiceDep) -> GammaEvent:
    return service.get_event_gamma(slug)
