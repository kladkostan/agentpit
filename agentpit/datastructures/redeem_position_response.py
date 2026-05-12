from pydantic import BaseModel


class RedeemPositionResponse(BaseModel):
    """`new_usdc_balance` is the post-redeem on-chain apUSD balance."""
    market_id: int
    collateral_amount: int = 0
    new_usdc_balance: int
