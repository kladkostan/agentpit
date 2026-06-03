from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.gamma_market import GammaEvent

router = APIRouter(tags=["events"])


@router.get("/events", response_model=list[GammaEvent])
def list_events(
    service: EventServiceDep, limit: int = 100, offset: int = 0
) -> list[GammaEvent]:
    return service.list_events_gamma(limit=limit, offset=offset)


@router.get("/events/{slug}", response_model=GammaEvent)
def get_event(slug: str, service: EventServiceDep) -> GammaEvent:
    return service.get_event_gamma(slug)
