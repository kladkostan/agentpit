from pydantic import BaseModel
from pydantic import field_validator, BaseModel
from agentpit.common import check_state


class RedeemPositionRequest(BaseModel):
    api_key: str

    def model_post_init(self, __context):
        check_state(self.api_key, "api_key must not be empty")


class ResolveMarketRequest(BaseModel):
    winning_outcome_index: int

    def model_post_init(self, __context):
        check_state(
            self.winning_outcome_index >= 0,
            "Winning outcome index must be non-negative",
        )
