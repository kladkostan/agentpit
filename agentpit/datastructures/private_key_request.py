from pydantic import BaseModel


class PrivateKeyRequest(BaseModel):
    """Exactly one of these, matching how the account signs in."""

    password: str | None = None
    google_credential: str | None = None


class PrivateKeyResponse(BaseModel):
    private_key: str
    eth_address: str
