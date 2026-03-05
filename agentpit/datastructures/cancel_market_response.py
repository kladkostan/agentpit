from pydantic import BaseModel
from agentpit.datastructures.market import Market


class CancelMarketResponse(BaseModel):
    """Response for cancelling a market."""
    market_id: int
    message: str
    refunds_processed: int
    market: Market
