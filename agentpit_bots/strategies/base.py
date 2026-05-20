"""Strategy abstract interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentpit_bots.reconcile import DesiredOrder


@dataclass(frozen=True)
class MarketTokens:
    """The minimal market info a strategy needs.

    The runner builds this from the `markets` table (local CTF token IDs)
    plus the `polymarket_yes_token_id` upstream IDs used by the oracle.
    """

    market_id: int
    yes_token_id: str  # local CTF id used in /orders
    no_token_id: str  # local CTF id used in /orders


class Strategy(ABC):
    @abstractmethod
    def compute_desired_orders(self, **kwargs) -> list[DesiredOrder]: ...
