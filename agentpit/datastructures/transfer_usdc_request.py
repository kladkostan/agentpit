from pydantic import field_validator, BaseModel
from .utils import check_state


class TransferUsdcRequest(BaseModel):
    api_key: str
    destination_address: str
    amount: int

    def model_post_init(self, __context):
        check_state(self.amount > 0, "Amount must be positive")
        check_state(len(self.destination_address) > 0, "Destination address must not be empty")
