from pydantic import BaseModel


class TradeResponse(BaseModel):
    trade_id: str
    market_id: int
    token_id: str
    price: int
    amount: int
    buyer_address: str
    seller_address: str
    timestamp: int  # unix timestamp
