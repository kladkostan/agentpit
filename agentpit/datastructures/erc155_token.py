from dataclasses import dataclass
from agentpit.utils.parse import is_hex256
from pydantic import BaseModel, field_validator
from agentpit.common import check_state


class erc1155Token(BaseModel):
    token_id: str
    label: str

    def model_post_init(self, __context):
        check_state(len(self.token_id) > 0, "Token ID must not be empty")
        check_state(len(self.label) > 0, "Label must not be empty")
