from pydantic import field_validator, BaseModel
from .utils import check_state


class UpdateMarketRequest(BaseModel):
    market_state: str

    def model_post_init(self, __context):
        check_state(len(self.market_state) > 0, "Market state must not be empty")
