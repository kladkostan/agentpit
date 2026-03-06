from pydantic import field_validator, BaseModel
from pydantic import field_validator, BaseModel
from agentpit.common import check_state


class RedeemPositionRequest(BaseModel):
    api_key: str

    def model_post_init(self, __context):
        check_state(self.api_key, "api_key must not be empty")




class SplitPositionRequest(BaseModel):
    api_key: str
    amount: int  # number of complete sets to split

    def model_post_init(self, __context):
        check_state(self.amount > 0, "Amount must be positive")
