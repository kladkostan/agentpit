from pydantic import BaseModel
from typing import Dict, List


class OrderbookEntry(BaseModel):
    price: int
    amount: int
    num_orders: int


class OrderbookResponse(BaseModel):
    market_id: int
    bids: Dict[str, List[OrderbookEntry]]  # token_id -> list of buy orders
    asks: Dict[str, List[OrderbookEntry]]  # token_id -> list of sell orders
