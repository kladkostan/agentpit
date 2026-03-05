from pydantic import BaseModel


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
