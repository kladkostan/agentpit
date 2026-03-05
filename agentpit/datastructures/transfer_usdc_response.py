from pydantic import BaseModel


class TransferUsdcResponse(BaseModel):
    from_address: str
    to_address: str
    amount: int
    new_balance: int
