from pydantic import field_validator, BaseModel


class TransferUsdcRequest(BaseModel):
    api_key: str
    destination_address: str
    amount: int
