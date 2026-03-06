from pydantic import BaseModel
from agentpit.common import check_state


class EthAddressResponse(BaseModel):
    api_key: str
    eth_address: str

    def model_post_init(self, __context):
        check_state(len(self.api_key) > 0,
                    "API key must not be empty")
        check_state(len(self.eth_address) > 0,
                    "ETH address must not be empty")
