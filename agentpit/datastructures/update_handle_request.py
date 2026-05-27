import re

from pydantic import BaseModel, field_validator


class UpdateHandleRequest(BaseModel):
    handle: str

    @field_validator("handle")
    @classmethod
    def _handle_format(cls, v: str) -> str:
        value = v.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,15}", value):
            raise ValueError("handle must be 1-15 chars, alphanumeric or underscore")
        return value
