from pydantic import field_validator, BaseModel
from agentpit.common import check_state


class MintUsdcRequest(BaseModel):
    api_key: str
    amount: int

    def model_post_init(self, __context):
        check_state(len(self.api_key) > 0, "API key must not be empty")
        check_state(self.amount > 0, "Amount must be positive")
