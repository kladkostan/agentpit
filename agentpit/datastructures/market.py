from dataclasses import dataclass
from agentpit.utils.parse import is_hex256


@dataclass(slots=True, init=False)
class Market:
    market_id: int
    condition_id: str
    description: str
    erc155_tokens: list[list[str]]  # list of [tokenId, label] pairs

    def __init__(
        self,
        market_id: int,
        condition_id: str,
        description: str,
        erc155_tokens: list[list[str]],
    ) -> None:
        if not isinstance(market_id, int) or market_id < 0:
            raise ValueError("market_id must be a non-negative int")
        if not isinstance(condition_id, str) or not condition_id:
            raise ValueError("condition_id must be a non-empty string")
        if not is_hex256(condition_id):
            raise ValueError("condition_id must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        if not isinstance(description, str) or not description:
            raise ValueError("description must be a non-empty string")
        if not isinstance(erc155_tokens, list):
            raise ValueError("erc155_tokens must be a list of [tokenId, label] pairs")
        for pair in erc155_tokens:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(x, str) and x for x in pair)
            ):
                raise ValueError("each token pair must be [non-empty str, non-empty str]")
        self.market_id = market_id
        self.condition_id = condition_id
        self.description = description
        self.erc155_tokens = erc155_tokens



