from pydantic import BaseModel, Field


class OrderBookLevel(BaseModel):
    """One aggregated price level (decimal strings, §8.5)."""

    price: str
    size: str


class OrderBookSummary(BaseModel):
    """CLOB `OrderBookSummary` (§8.5). Prices/sizes are decimal strings;
    `market` is the condition_id, `asset_id` the token_id."""

    market: str
    asset_id: str
    timestamp: str                      # ms epoch string
    hash: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    min_order_size: str = "0"
    tick_size: str = "0.001"
    neg_risk: bool = False
    last_trade_price: str = "0"
