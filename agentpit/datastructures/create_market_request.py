from pydantic import BaseModel
import time

from agentpit.datastructures.market_state import MarketState
from agentpit.utils.check_state import check_state  # Adjust import path as needed


class CreateMarketRequest(BaseModel):
    question: str
    description: str
    erc1155_tokens: list[tuple[str, str]]
    slug: str = ""
    start_date: int = None
    end_date: int | None = None
    polymarket_id: int | None = None
    state: MarketState = MarketState.DRAFT

    def model_post_init(self, __context):
        check_state(len(self.question) > 0,
                    "Question must not be empty")
        check_state(len(self.description) > 0,
                    "Description must not be empty")
        check_state(len(self.erc1155_tokens) > 0,
                    "ERC1155 tokens list must not be empty")
        if self.start_date is not None and self.end_date is not None:
            check_state(self.end_date >= self.start_date,
                        "End date must be after or equal to start date")
