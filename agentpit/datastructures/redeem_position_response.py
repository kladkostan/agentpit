from pydantic import BaseModel


class RedeemPositionResponse(BaseModel):
    market_id: int
    payout_usdc: int
    tokens_redeemed: dict[str, int]  # token_id -> amount redeemed
