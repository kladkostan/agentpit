from pydantic import BaseModel, field_validator


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("current_password")
    @classmethod
    def _current_password_required(cls, v: str) -> str:
        if not v:
            raise ValueError("current_password is required")
        return v

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(v) > 256:
            raise ValueError("password too long")
        return v
