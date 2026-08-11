from pydantic import BaseModel


class UserPublic(BaseModel):
    user_id: str
    email: str
    handle: str | None
    eth_address: str
    api_key: str
    onboarded_at: int | None
    created_at: int
    has_password: bool
    auto_redeem: bool


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Present only on the AuthKit paths. The legacy `/register` and `/login`
    # issue a 24-hour JwtCoder token with nothing to refresh, so they leave
    # this null rather than growing a second response model.
    refresh_token: str | None = None
    user: UserPublic


class GoogleAuthResponse(AuthResponse):
    """`AuthResponse` plus whether this sign-in created the account.

    The password path greets a new user with "your wallet is funded"; without
    this flag the Google path cannot tell a first sign-in from a returning one,
    and either every user gets the greeting or nobody does.
    """

    created: bool
