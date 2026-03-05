from pydantic import field_validator, BaseModel

from agentpit.utils.parse import is_hex256


class CreateMarketRequest(BaseModel):
    condition_id: str
    description: str
    erc155_tokens: list[tuple[str, str]]

    @field_validator("condition_id")
    @classmethod
    def validate_condition_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        if not is_hex256(v):
            raise ValueError("must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("erc155_tokens")
    @classmethod
    def validate_erc155_tokens(cls, v: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not isinstance(v, list):
            raise ValueError("must be a list of [tokenId, label] pairs")
        for pair in v:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(isinstance(x, str) and x for x in pair)
            ):
                raise ValueError("each token pair must be a tuple or list of two non-empty strings")
        return v
