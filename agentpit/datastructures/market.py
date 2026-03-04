from typing import Optional, Any
from pydantic import BaseModel, field_validator
from agentpit.db.table_create import MarketState
from agentpit.utils.parse import is_hex256


class Market(BaseModel):
    question: str
    market_id: int
    condition_id: str
    description: str
    erc155_tokens: list[tuple[str, str]]
    start_date: Optional[int] = None
    end_date: Optional[int] = None
    resolved_outcome: Optional[int] = None
    market_state: MarketState

    @field_validator("question", "description")
    @classmethod
    def check_non_empty_str(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("market_id", "start_date", "end_date", "resolved_outcome")
    @classmethod
    def check_non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (not isinstance(v, int) or v < 0):
            raise ValueError("must be a non-negative integer")
        return v

    @field_validator("condition_id")
    @classmethod
    def check_condition_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        if not is_hex256(v):
            raise ValueError("must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        return v

    @field_validator("erc155_tokens")
    @classmethod
    def check_erc155_tokens(cls, v: Any) -> list[tuple[str, str]]:
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

    @field_validator("market_state")
    @classmethod
    def check_market_state(cls, v: Any) -> MarketState:
        if not isinstance(v, MarketState):
            raise ValueError(f"must be a MarketState enum member, not {type(v)}")
        return v
