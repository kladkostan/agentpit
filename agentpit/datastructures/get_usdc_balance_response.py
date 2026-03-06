from pydantic import BaseModel
from agentpit.common import check_state


class GetUsdcBalanceResponse(BaseModel):
    eth_address: str
    balance: int

    def model_post_init(self, __context):
        check_state(len(self.eth_address) > 0,
                    "ETH address must not be empty")
        check_state(self.balance >= 0,
                    "Balance must be non-negative")
