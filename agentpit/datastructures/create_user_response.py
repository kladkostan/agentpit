from pydantic import BaseModel
from agentpit.common import check_state


class CreateUserResponse(BaseModel):
    user_id: str
    api_key: str
    eth_address: str

    def model_post_init(self, __context):
        check_state(len(self.user_id) > 0, "user_id must not be empty")
        check_state(len(self.api_key) > 0, "api_key must not be empty")
        check_state(len(self.eth_address) > 0, "eth_address must not be empty")

