from pydantic import field_validator, BaseModel


class PlaceOrderRequest(BaseModel):
    api_key: str
    market_id: int
    side: str  # "BUY" or "SELL"
    token_id: str
    price: int  # in USDC
    amount: int  # quantity
    order_type: str = "LIMIT"  # "LIMIT" or "MARKET"

