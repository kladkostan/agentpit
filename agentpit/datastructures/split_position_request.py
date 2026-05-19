from pydantic import BaseModel, Field


class SplitPositionRequest(BaseModel):
    """Lock `amount` apUSD on-chain to mint equal amounts of every outcome token."""

    amount: int = Field(gt=0)


class MergePositionRequest(BaseModel):
    """Burn `amount` of each outcome token to recover `amount` apUSD."""

    amount: int = Field(gt=0)
