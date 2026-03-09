from pydantic import BaseModel
import time

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.condition_id import compute_condition_id


class CreateMarketRequest(BaseModel):
    question: str
    description: str
    erc1155_tokens: list[tuple[str, str]]
    slug: str = ""
    start_date: int | None = None
    end_date: int | None = None
    polymarket_id: int | None = None
    condition_id: ConditionId | None = None
    state: MarketState = MarketState.DRAFT

    def model_post_init(self, __context):

        if not self.slug:
            self.slug = self.question.lower().replace(" ", "-").replace("?", "")
            # Use current timestamp if start_date not provided
        if self.start_date is None:
            self.start_date = int(time.time())

        check_state(len(self.question) > 0,
                    "Question must not be empty")
        check_state(len(self.description) > 0,
                    "Description must not be empty")
        check_state(len(self.erc1155_tokens) > 0,
                    "ERC1155 tokens list must not be empty")
        if self.start_date is not None and self.end_date is not None:
            check_state(self.end_date >= self.start_date,
                        "End date must be after or equal to start date")


