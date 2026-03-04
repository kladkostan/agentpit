from dataclasses import dataclass
from agentpit_clob.utils.parse import is_hex256


@dataclass(slots=True, init=False)
class ERC155Token:
    token_id: str
    label: str

    def __init__(self, token_id: str, label: str) -> None:
        if not isinstance(token_id, str) or not token_id:
            raise ValueError("token_id must be a non-empty string")
        if not isinstance(label, str) or not label:
            raise ValueError("label must be a non-empty string")
        if not is_hex256(token_id):
            raise ValueError("token_id must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        self.token_id = token_id
        self.label = label
