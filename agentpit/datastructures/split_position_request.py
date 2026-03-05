from pydantic import field_validator, BaseModel


class SplitPositionRequest(BaseModel):
    api_key: str
    amount: int  # number of complete sets to split

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if not isinstance(v, int) or v <= 0:
            raise ValueError("must be a positive integer")
        return v
