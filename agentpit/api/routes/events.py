from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.event_with_markets import (
    EventWithMarkets,
    ListEventCategoriesResponse,
    ListEventsResponse,
)

router = APIRouter(tags=["events"])


@router.get("/events", response_model=ListEventsResponse)
def list_events(
    service: EventServiceDep,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
) -> ListEventsResponse:
    return service.list_events(limit=limit, offset=offset, category=category)


@router.get("/events/categories", response_model=ListEventCategoriesResponse)
def list_event_categories(service: EventServiceDep) -> ListEventCategoriesResponse:
    return service.list_categories()


@router.get("/events/{slug}", response_model=EventWithMarkets)
def get_event(slug: str, service: EventServiceDep) -> EventWithMarkets:
    return service.get_event_by_slug(slug)
