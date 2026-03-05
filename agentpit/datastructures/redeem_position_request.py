from pydantic import field_validator, BaseModel


class RedeemPositionRequest(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v
