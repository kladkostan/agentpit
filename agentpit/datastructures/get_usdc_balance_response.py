from pydantic import BaseModel


class GetUsdcBalanceResponse(BaseModel):
    eth_address: str
    balance: int
