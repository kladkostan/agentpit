from pydantic import BaseModel
from agentpit.common import check_state


class RedeemPositionResponse(BaseModel):
    market_id: int
    payout_usdc: int
    tokens_redeemed: dict[str, int]  # token_id -> amount redeemed

    def model_post_init(self, __context):
        check_state(self.market_id >= 0, "Market ID must be non-negative")
        check_state(self.payout_usdc >= 0, "Payout USDC must be non-negative")
        check_state(self.tokens_redeemed is not None, "Tokens redeemed must not be None")
        for token_id, amount in self.tokens_redeemed.items():
            check_state(len(token_id) > 0, "Token ID must not be empty")
            check_state(amount >= 0, f"Amount for token {token_id} must be non-negative")
