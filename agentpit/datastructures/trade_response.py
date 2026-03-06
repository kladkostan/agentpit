from pydantic import BaseModel
from agentpit.utils import check_state


class TradeResponse(BaseModel):
    trade_id: str
    market_id: int
    token_id: str
    price: int
    amount: int
    buyer_address: str
    seller_address: str
    timestamp: int  # unix timestamp

    def model_post_init(self, __context):
        check_state(len(self.trade_id) > 0, "Trade ID must not be empty")
        check_state(self.market_id >= 0, "Market ID must be non-negative")
        check_state(len(self.token_id) > 0, "Token ID must not be empty")
        check_state(self.price >= 0, "Price must be non-negative")
        check_state(self.amount > 0, "Amount must be positive")
        check_state(len(self.buyer_address) > 0, "Buyer address must not be empty")
        check_state(len(self.seller_address) > 0, "Seller address must not be empty")
        check_state(self.timestamp > 0, "Timestamp must be positive")
