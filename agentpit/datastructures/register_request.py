import re

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    handle: str | None = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(v) > 256:
            raise ValueError("password too long")
        return v

    @field_validator("handle")
    @classmethod
    def _handle_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,15}", v):
            raise ValueError("handle must be 1-15 chars, alphanumeric or underscore")
        return v
