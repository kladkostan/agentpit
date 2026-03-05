from pydantic import BaseModel


class Position(BaseModel):
    market_id: int
    token_id: str
    token_label: str
    balance: int
