from pydantic import BaseModel
from agentpit.utils import check_state


class ResolveMarketRequest(BaseModel):
    winning_outcome_index: int

    def model_post_init(self, __context):
        check_state(self.winning_outcome_index >= 0, "Winning outcome index must be non-negative")
