from pydantic import BaseModel


class PositionWire(BaseModel):
    """Data-API position object (§8.8); floats, with defensible defaults so
    partial data still serializes the exact Polymarket shape."""

    proxyWallet: str = ""
    asset: str = ""              # token_id
    conditionId: str = ""
    size: float = 0.0
    avgPrice: float = 0.0
    initialValue: float = 0.0
    currentValue: float = 0.0
    cashPnl: float = 0.0
    percentPnl: float = 0.0
    totalBought: float = 0.0
    realizedPnl: float = 0.0
    percentRealizedPnl: float = 0.0
    curPrice: float = 0.0
    redeemable: bool = False
    title: str = ""
    slug: str = ""
    icon: str = ""
    eventSlug: str = ""
    outcome: str = ""
    outcomeIndex: int = 0
    oppositeOutcome: str = ""
    oppositeAsset: str = ""
    endDate: str = ""
    negativeRisk: bool = False
