from pydantic import field_validator, BaseModel

from agentpit.utils.parse import is_hex256


class CreateMarketRequest(BaseModel):
    question: str
    description: str
    erc1155_tokens: list[tuple[str, str]]
    slug: str
    start_date: int
    end_date: int
    polymarket_id: int | None = None

