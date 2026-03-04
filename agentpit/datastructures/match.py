from pydantic import BaseModel, field_validator

class Match(BaseModel):
    taker_order_id: str
    maker_order_id: str
    price: int
    trade_size: int

    @field_validator("taker_order_id", "maker_order_id")
    @classmethod
    def check_non_empty_str(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("price", "trade_size")
    @classmethod
    def check_non_negative_int(cls, v: int) -> int:
        if not isinstance(v, int) or v < 0:
            raise ValueError("must be a non-negative int")
        return v
