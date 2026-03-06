from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, field_validator
from agentpit.common import check_state

class OrderResponse(BaseModel):
    success: bool
    orderID: str
    status: str
    filledSize: str
    remainingSize: str
    avgPrice: Optional[str]
    errorMsg: Optional[str]

    def model_post_init(self, __context):
        check_state(len(self.orderID) > 0,
                    "Order ID must not be empty")
        check_state(len(self.status) > 0,
                    "Status must not be empty")
        check_state(len(self.filledSize) > 0,
                    "Filled size must not be empty")
        check_state(len(self.remainingSize) > 0,
                    "Remaining size must not be empty")
