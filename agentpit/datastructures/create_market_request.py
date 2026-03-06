from pydantic import BaseModel
import time

from agentpit.datastructures.market_state import MarketState


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
        # Auto-generate slug from question if not provided
        if not self.slug:
            self.slug = self.question.lower().replace(" ", "-").replace("?", "")
        # Use current timestamp if start_date not provided
        if self.start_date is None:
            self.start_date = int(time.time())

