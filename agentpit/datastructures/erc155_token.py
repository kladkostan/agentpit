from dataclasses import dataclass
from agentpit.utils.parse import is_hex256
from pydantic import BaseModel, field_validator


class erc1155Token(BaseModel):
    token_id: str
    label: str

    @field_validator("token_id")
    @classmethod
    def check_token_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("token_id must be a non-empty string")
        if not is_hex256(v):
            raise ValueError("token_id must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        return v

    @field_validator("label")
    @classmethod
    def check_label(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("label must be a non-empty string")
        return v
