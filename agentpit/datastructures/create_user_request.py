from pydantic import BaseModel
from agentpit.common import check_state
import re


class CreateUserRequest(BaseModel):
    user_id: str

    def model_post_init(self, __context):
        check_state(
            bool(re.match(r"^[a-zA-Z0-9_]{1,15}$", self.user_id)),
            "user_id must be a valid handle (1-15 characters, alphanumeric or underscores only)",
        )

