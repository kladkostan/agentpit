from pydantic import BaseModel


class MintUsdcResponse(BaseModel):
    eth_address: str
    amount: int
    new_balance: int
