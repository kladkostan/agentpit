from typing import Optional, Any
from pydantic import BaseModel, field_validator

from agentpit.common import check_state
from agentpit.db.table_create import MarketState
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework
from agentpit.utils.parse import is_hex256


class Market(BaseModel):
    question: str
    slug: str
    market_id: int
    polymarket_id: Optional[int] = None
    condition_id: str
    description: str
    erc1155_tokens: list[tuple[str, str]]
    start_date: int
    end_date: Optional[int | None]
    resolved_outcome: Optional[int] = None
    market_state: MarketState






