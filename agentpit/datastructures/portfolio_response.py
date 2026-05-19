from pydantic import BaseModel
from typing import List
from agentpit.common import check_state


class Position(BaseModel):
    """Represents a user's holding of a specific outcome token."""

    market_id: int
    question: str
    token_id: str
    outcome_label: str
    outcome_index: int
    balance: int

    def model_post_init(self, __context):
        check_state(self.market_id >= 0, "Market ID must be non-negative")
        check_state(len(self.question) > 0, "Question must not be empty")
        check_state(len(self.token_id) > 0, "Token ID must not be empty")
        check_state(len(self.outcome_label) > 0, "Outcome label must not be empty")
        check_state(self.outcome_index >= 0, "Outcome index must be non-negative")
        check_state(self.balance >= 0, "Balance must be non-negative")


class PortfolioResponse(BaseModel):
    """Summary of a user's holdings."""

    eth_address: str
    usdc_balance: int
    positions: List[Position]

    def model_post_init(self, __context):
        check_state(len(self.eth_address) > 0, "ETH address must not be empty")
        check_state(self.usdc_balance >= 0, "USDC balance must be non-negative")
