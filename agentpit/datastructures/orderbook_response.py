from pydantic import BaseModel
from typing import Dict, List
from agentpit.common import check_state


class OrderbookEntry(BaseModel):
    price: int
    amount: int
    num_orders: int

    def model_post_init(self, __context):
        check_state(self.price >= 0,
                    "Price must be non-negative")
        check_state(self.amount >= 0,
                    "Amount must be non-negative")
        check_state(self.num_orders >= 0,
                    "Number of orders must be non-negative")


class OrderbookResponse(BaseModel):
    market_id: int
    bids: Dict[str, List[OrderbookEntry]]  # token_id -> list of buy orders
    asks: Dict[str, List[OrderbookEntry]]  # token_id -> list of sell orders

    def model_post_init(self, __context):
        check_state(self.market_id >= 0,
                    "Market ID must be non-negative")
