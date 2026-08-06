from pydantic import BaseModel


class UserPublic(BaseModel):
    user_id: str
    email: str
    handle: str | None
    eth_address: str
    api_key: str
    onboarded_at: int | None
    created_at: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class GoogleAuthResponse(AuthResponse):
    """`AuthResponse` plus whether this sign-in created the account.

    The password path greets a new user with "your wallet is funded"; without
    this flag the Google path cannot tell a first sign-in from a returning one,
    and either every user gets the greeting or nobody does.
    """

    created: bool
