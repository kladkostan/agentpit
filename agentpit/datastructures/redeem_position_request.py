from pydantic import BaseModel
from agentpit.common import check_state


class RedeemPositionRequest(BaseModel):
    api_key: str

    def model_post_init(self, __context):
        check_state(len(self.api_key) > 0, "api_key must not be empty")
