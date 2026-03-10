from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    eth_key: LocalAccount
    api_key: str

