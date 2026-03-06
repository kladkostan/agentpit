from pydantic import BaseModel, field_validator

class Match(BaseModel):
    taker_order_id: str
    maker_order_id: str
    price: int
    trade_size: int

