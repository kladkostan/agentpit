from pydantic import field_validator, BaseModel


class RedeemPositionRequest(BaseModel):
    api_key: str
