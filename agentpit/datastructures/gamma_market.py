"""Polymarket Gamma-API wire models (the practical subset agentpit serves).

Field names + casing match Gamma exactly. `outcomes`, `outcomePrices`, and
`clobTokenIds` are JSON arrays ENCODED AS STRINGS — that is Gamma's actual
wire format, replicated here so a bot parses agentpit identically to Polymarket.
"""

from typing import List, Optional

from pydantic import BaseModel


class GammaMarket(BaseModel):
    id: str
    conditionId: str
    question: str
    slug: str
    description: str
    outcomes: str            # JSON-encoded array, e.g. '["Yes","No"]'
    outcomePrices: str       # JSON-encoded array, e.g. '["0.5","0.5"]'
    clobTokenIds: str        # JSON-encoded array of token ids
    active: bool
    closed: bool
    acceptingOrders: bool
    startDate: Optional[str]
    endDate: Optional[str]
    endDateIso: Optional[str]
    icon: Optional[str]
    image: Optional[str]
    volume: str
    liquidity: str
    bestBid: float
    bestAsk: float
    lastTradePrice: float
    spread: float


class GammaEvent(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    icon: Optional[str]
    category: Optional[str]
    startDate: Optional[str]
    endDate: Optional[str]
    markets: List[GammaMarket]
