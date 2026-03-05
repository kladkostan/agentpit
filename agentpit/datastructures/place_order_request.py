from pydantic import field_validator, BaseModel


class PlaceOrderRequest(BaseModel):
    api_key: str
    market_id: int
    side: str  # "BUY" or "SELL"
    token_id: str
    price: int  # in USDC
    amount: int  # quantity
    order_type: str = "LIMIT"  # "LIMIT" or "MARKET"

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("market_id")
    @classmethod
    def validate_market_id(cls, v: int) -> int:
        if not isinstance(v, int) or v < 1:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ["BUY", "SELL"]:
            raise ValueError("must be 'BUY' or 'SELL'")
        return v

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: int) -> int:
        if not isinstance(v, int) or v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if not isinstance(v, int) or v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v: str) -> str:
        if v not in ["LIMIT", "MARKET"]:
            raise ValueError("must be 'LIMIT' or 'MARKET'")
        return v
