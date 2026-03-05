from pydantic import BaseModel
from agentpit.datastructures.market import Market


class ListMarketsResponse(BaseModel):
    markets: list[Market]
    total: int
    limit: int
    offset: int
