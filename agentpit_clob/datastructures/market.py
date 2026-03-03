from dataclasses import dataclass


@dataclass
class Market:
    market_id: int
    condition_id: str
    description: str
    erc155_tokens: list  # list of [tokenId, label] pairs
