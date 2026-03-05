from pydantic import BaseModel
from typing import List

class Position(BaseModel):
    """Represents a user's holding of a specific outcome token."""
    market_id: int
    question: str
    token_id: str
    outcome_label: str
    outcome_index: int
    balance: int

class PortfolioResponse(BaseModel):
    """Summary of a user's holdings."""
    eth_address: str
    usdc_balance: int
    positions: List[Position]

