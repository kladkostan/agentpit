from pydantic import BaseModel
from agentpit.utils import check_state


class TransferUsdcResponse(BaseModel):
    from_address: str
    to_address: str
    amount: int
    new_balance: int

    def model_post_init(self, __context):
        check_state(len(self.from_address) > 0, "From address must not be empty")
        check_state(len(self.to_address) > 0, "To address must not be empty")
        check_state(self.amount > 0, "Amount must be positive")
        check_state(self.new_balance >= 0, "New balance must be non-negative")
