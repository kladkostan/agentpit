from pydantic import BaseModel
from agentpit.datastructures.market import Market
from agentpit.common import check_state


class ListMarketsResponse(BaseModel):
    markets: list[Market]
    total: int
    limit: int
    offset: int

    def model_post_init(self, __context):
        check_state(self.total >= 0, "Total must be non-negative")
        check_state(self.limit > 0, "Limit must be positive")
        check_state(self.offset >= 0, "Offset must be non-negative")
        check_state(
            len(self.markets) <= self.limit, "Number of markets cannot exceed limit"
        )
