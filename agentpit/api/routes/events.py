import time

from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.gamma_market import GammaEvent

router = APIRouter(tags=["events"])

# Short-TTL response cache for the event listing. The home page polls /events
# every few seconds; without a cache, N clients = N DB reads per interval even
# though the list only changes when a sync runs. With it, a poll burst collapses
# to ~one DB read per TTL window, regardless of client count. Keyed by
# (limit, offset); per-process; staleness is bounded by the TTL.
_EVENTS_TTL_S = 3.0
_events_cache: dict[tuple[int, int], tuple[float, list[GammaEvent]]] = {}


def _list_events_cached(
    service, *, limit: int, offset: int, now: float
) -> list[GammaEvent]:
    """Return the cached page if it is younger than the TTL, else fetch + store.

    `now` is injected (monotonic seconds) so the TTL is deterministically
    testable. The sync `def` route runs in FastAPI's threadpool; dict get/set
    are atomic in CPython, so no lock is needed — a rare concurrent miss just
    does one extra harmless DB read.
    """
    key = (limit, offset)
    hit = _events_cache.get(key)
    if hit is not None and now - hit[0] < _EVENTS_TTL_S:
        return hit[1]
    result = service.list_events_gamma(limit=limit, offset=offset)
    _events_cache[key] = (now, result)
    return result


@router.get("/events", response_model=list[GammaEvent])
def list_events(
    service: EventServiceDep, limit: int = 100, offset: int = 0
) -> list[GammaEvent]:
    return _list_events_cached(
        service, limit=limit, offset=offset, now=time.monotonic()
    )


@router.get("/events/{slug}", response_model=GammaEvent)
def get_event(slug: str, service: EventServiceDep) -> GammaEvent:
    return service.get_event_gamma(slug)
