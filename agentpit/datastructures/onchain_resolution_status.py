from dataclasses import dataclass
from typing import List, Optional

from agentpit.common import check_state


@dataclass
class OnchainResolutionStatus:
    payouts: List[int]
    denominator: int
    resolved: bool

    def __post_init__(self):
        check_state(not self.resolved or self.get_winner_index() is not None)

    def get_winner_index(self) -> Optional[int]:
        if not self.resolved:
            return None
        for i, payout in enumerate(self.payouts):
            if payout == self.denominator:
                return i
        return None

