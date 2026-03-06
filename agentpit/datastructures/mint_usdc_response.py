from pydantic import BaseModel
from agentpit.common import check_state


class MintUsdcResponse(BaseModel):
    eth_address: str
    amount: int
    new_balance: int

    def model_post_init(self, __context):
        check_state(len(self.eth_address) > 0,
                    "ETH address must not be empty")
        check_state(self.amount > 0,
                    "Amount must be positive")
        check_state(self.new_balance >= 0,
                    "New balance must be non-negative")
