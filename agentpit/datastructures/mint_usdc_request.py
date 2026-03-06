from pydantic import field_validator, BaseModel


class MintUsdcRequest(BaseModel):
    api_key: str
    amount: int

