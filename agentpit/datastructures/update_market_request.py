from pydantic import field_validator, BaseModel


class UpdateMarketRequest(BaseModel):
    market_state: str

    @field_validator("market_state")
    @classmethod
    def validate_market_state(cls, v: str) -> str:
        valid_states = ["DRAFT", "ACTIVE", "CLOSED", "RESOLVED", "CANCELLED"]
        if v not in valid_states:
            raise ValueError(f"must be one of {valid_states}")
        return v
