from pydantic import BaseModel
from agentpit.common import check_state


class Order(BaseModel):
    order_id: str
    api_key: str
    market_id: int
    side: str  # "BUY" or "SELL"
    token_id: str
    price: int
    amount: int
    remaining_amount: int
    status: str  # "LIVE", "FILLED", "CANCELLED"
    order_type: str  # "LIMIT" or "MARKET"
    created_at: int  # unix timestamp

    def model_post_init(self, __context):
        check_state(len(self.order_id) > 0, "Order ID must not be empty")
        check_state(len(self.api_key) > 0, "API key must not be empty")
        check_state(self.market_id >= 0, "Market ID must be non-negative")
        check_state(self.side in ["BUY", "SELL"], "Side must be either BUY or SELL")
        check_state(len(self.token_id) > 0, "Token ID must not be empty")
        check_state(self.price >= 0, "Price must be non-negative")
        check_state(self.amount > 0, "Amount must be positive")
        check_state(self.remaining_amount >= 0, "Remaining amount must be non-negative")
        check_state(
            self.status in ["LIVE", "FILLED", "CANCELLED"],
            "Status must be LIVE, FILLED, or CANCELLED",
        )
        check_state(
            self.order_type in ["LIMIT", "MARKET"], "Order type must be LIMIT or MARKET"
        )
        check_state(self.created_at > 0, "Created at must be positive")
