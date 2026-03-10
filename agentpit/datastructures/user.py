import re
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, ConfigDict
from agentpit.common import check_state


class User(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    eth_key: LocalAccount
    api_key: str

    def model_post_init(self, __context):
        # Twitter handle format: alphanumeric and underscores, 1-15 characters
        check_state(
            bool(re.match(r"^[a-zA-Z0-9_]{1,15}$", self.user_id)),
            "user_id must be a valid handle (1-15 characters, alphanumeric or underscores only)",
        )
