from pydantic import BaseModel
from agentpit.common import check_state


class PositionResponse(BaseModel):
    market_id: int
    amount: int  # number of complete sets
    collateral_amount: int  # USDC amount locked/unlocked
    token_balances: dict[str, int]  # token_id -> new balance

    def model_post_init(self, __context):
        check_state(self.market_id >= 0, "Market ID must be non-negative")
        check_state(self.amount >= 0, "Amount must be non-negative")
        check_state(
            self.collateral_amount >= 0, "Collateral amount must be non-negative"
        )
