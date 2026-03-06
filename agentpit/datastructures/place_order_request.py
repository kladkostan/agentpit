from pydantic import field_validator, BaseModel
from agentpit.common import check_state


class PlaceOrderRequest(BaseModel):
    api_key: str
    market_id: int
    side: str  # "BUY" or "SELL"
    token_id: str
    price: int  # in USDC
    amount: int  # quantity
    order_type: str = "LIMIT"  # "LIMIT" or "MARKET"

    def model_post_init(self, __context):
        check_state(len(self.api_key) > 0,
                    "API key must not be empty")
        check_state(self.market_id >= 0,
                    "Market ID must be non-negative")
        check_state(self.side in ["BUY", "SELL"],
                    "Side must be either BUY or SELL")
        check_state(len(self.token_id) > 0,
                    "Token ID must not be empty")
        check_state(self.price >= 0,
                    "Price must be non-negative")
        check_state(self.amount > 0,
                    "Amount must be positive")
        check_state(self.order_type in ["LIMIT", "MARKET"],
                    "Order type must be LIMIT or MARKET")
