from pydantic import field_validator, BaseModel


class UpdateMarketRequest(BaseModel):
    market_state: str

