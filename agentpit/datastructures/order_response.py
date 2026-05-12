from typing import Optional

from pydantic import BaseModel

from agentpit.common import check_state


class OrderResponse(BaseModel):
    """Response returned by /orders. Field names are camelCase for client compat."""

    success: bool
    orderID: str
    status: str
    filledSize: str
    remainingSize: str
    avgPrice: Optional[str] = None
    errorMsg: Optional[str] = None
    txHash: Optional[str] = None

    def model_post_init(self, __context):
        check_state(len(self.orderID) > 0, "Order ID must not be empty")
        check_state(len(self.status) > 0, "Status must not be empty")
        check_state(len(self.filledSize) > 0, "Filled size must not be empty")
        check_state(len(self.remainingSize) > 0, "Remaining size must not be empty")
