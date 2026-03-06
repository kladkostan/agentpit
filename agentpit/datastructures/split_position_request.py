from pydantic import field_validator, BaseModel
from .utils import check_state


class SplitPositionRequest(BaseModel):
    api_key: str
    amount: int  # number of complete sets to split

    def model_post_init(self, __context):
        check_state(self.amount > 0, "Amount must be positive")
