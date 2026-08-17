from pydantic import BaseModel, Field


class PrivateKeyRequest(BaseModel):
    """The code just mailed to the account's own address.

    One factor for every account. It replaces the password-or-Google pair,
    which chose by what the row HAD -- a rule that could not survive accounts
    having neither.
    """

    # Six digits, as WorkOS issues them. Validated here so an obviously
    # malformed code costs a 422 rather than a round-trip to WorkOS.
    code: str = Field(pattern=r"^\d{6}$")


class PrivateKeyResponse(BaseModel):
    private_key: str
    eth_address: str
