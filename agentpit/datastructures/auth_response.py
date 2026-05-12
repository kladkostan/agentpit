from pydantic import BaseModel


class UserPublic(BaseModel):
    user_id: str
    email: str
    handle: str | None
    eth_address: str
    onboarded_at: int | None
    created_at: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
