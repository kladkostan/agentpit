from pydantic import BaseModel
from agentpit.datastructures.market import Market
from agentpit.common import check_state


class CancelMarketResponse(BaseModel):
    """Response for cancelling a market."""
    market_id: int
    message: str
    refunds_processed: int
    market: Market

    def model_post_init(self, __context):
        check_state(self.refunds_processed >= 0,
                    "Refunds processed must be non-negative")
        check_state(len(self.message) > 0,
                    "Message must not be empty")
