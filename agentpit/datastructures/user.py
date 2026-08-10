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
    # No default: `_row_to_user` is the only construction site and always
    # supplies this. A defaulted value fails OPEN -- it would show the
    # Google-only export control to a password account if a caller ever
    # forgot to pass it.
    has_password: bool

    def model_post_init(self, __context):
        if self.handle is not None:
            check_state(
                bool(re.match(r"^[a-zA-Z0-9_]{1,15}$", self.handle)),
                "handle must be a valid handle (1-15 characters, alphanumeric or underscores only)",
            )
