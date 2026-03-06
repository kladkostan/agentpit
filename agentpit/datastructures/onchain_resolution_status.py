from dataclasses import dataclass
from typing import List, Optional


@dataclass
class OnchainResolutionStatus:
    payouts: List[int]
    denominator: int
    resolved: bool

    def get_winner_index(self) -> Optional[int]:
        if not self.resolved:
            return None
        for i, payout in enumerate(self.payouts):
            if payout == self.denominator:
                return i

