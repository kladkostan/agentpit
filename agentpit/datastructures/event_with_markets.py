from pydantic import BaseModel

from agentpit.datastructures.event import Event
from agentpit.datastructures.market import Market


class EventWithMarkets(BaseModel):
    event: Event
    markets: list[Market]


class ListEventsResponse(BaseModel):
    events: list[EventWithMarkets]
    total: int
    limit: int
    offset: int


class ListEventCategoriesResponse(BaseModel):
    categories: list[str]
