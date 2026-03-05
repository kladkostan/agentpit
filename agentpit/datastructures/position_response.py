from pydantic import BaseModel


class PositionResponse(BaseModel):
    market_id: int
    amount: int  # number of complete sets
    collateral_amount: int  # USDC amount locked/unlocked
    token_balances: dict[str, int]  # token_id -> new balance
