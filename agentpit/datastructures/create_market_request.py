from pydantic import BaseModel
import time

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.market_state import MarketState


class CreateMarketRequest(BaseModel):
    question: str
    description: str
    # For local creation, leave erc1155_tokens empty and supply outcome_labels —
    # the service will derive tokenIds from on-chain prepareCondition. The
    # Polymarket sync path supplies the full erc1155_tokens list directly.
    erc1155_tokens: list[tuple[str, str]] = []
    outcome_labels: list[str] | None = None
    slug: str = ""
    start_date: int | None = None
    end_date: int | None = None
    polymarket_id: int | None = None
    polymarket_condition_id: str | None = None
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
        # Either outcome_labels (for local on-chain creation) or erc1155_tokens
        # (for Polymarket sync) must be supplied.
        check_state(
            self.outcome_labels is not None or len(self.erc1155_tokens) > 0,
            "Provide outcome_labels (local) or erc1155_tokens (sync)",
        )
        if self.outcome_labels is not None:
            check_state(
                len(self.outcome_labels) >= 2,
                "Need at least 2 outcome labels",
            )
        if self.start_date is not None and self.end_date is not None:
            check_state(self.end_date >= self.start_date,
                        "End date must be after or equal to start date")


