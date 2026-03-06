from pydantic import BaseModel
from agentpit.common import check_state


class Position(BaseModel):
    market_id: int
    token_id: str
    token_label: str
    balance: int

    def model_post_init(self, __context):
        check_state(self.market_id >= 0,
                    "Market ID must be non-negative")
        check_state(len(self.token_id) > 0,
                    "Token ID must not be empty")
        check_state(len(self.token_label) > 0,
                    "Token label must not be empty")
        check_state(self.balance >= 0,
                    "Balance must be non-negative")
