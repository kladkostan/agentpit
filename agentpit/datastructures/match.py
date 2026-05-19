from pydantic import BaseModel, field_validator
from agentpit.common import check_state


class Match(BaseModel):
    taker_order_id: str
    maker_order_id: str
    price: int
    trade_size: int

    def model_post_init(self, __context):
        check_state(len(self.taker_order_id) > 0, "Taker order ID must not be empty")
        check_state(len(self.maker_order_id) > 0, "Maker order ID must not be empty")
        check_state(self.price > 0, "Price must be positive")
        check_state(self.trade_size > 0, "Trade size must be positive")
