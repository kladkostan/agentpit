import re
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, ConfigDict
from agentpit.common import check_state


class User(BaseModel):
    """Internal user record. Email + password are auth credentials; eth_key is server-held."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    email: str
    eth_key: LocalAccount
    eth_address: str
    api_key: str
    handle: str | None = None
    onboarded_at: int | None = None
    created_at: int
    is_bot: bool = False
    has_password: bool = False

    def model_post_init(self, __context):
        if self.handle is not None:
            check_state(
                bool(re.match(r"^[a-zA-Z0-9_]{1,15}$", self.handle)),
                "handle must be a valid handle (1-15 characters, alphanumeric or underscores only)",
            )
