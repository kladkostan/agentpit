from dataclasses import dataclass
from agentpit.utils.parse import is_hex256
from pydantic import BaseModel, field_validator


class erc1155Token(BaseModel):
    token_id: str
    label: str
