from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PlaceOrderRequest(BaseModel):
    """Inputs for the simple-trade UX: pick outcome, side, price and size."""

    market_id: int = Field(ge=0)
    outcome: str = Field(
        min_length=1
    )  # e.g. "YES" / "NO" — looked up against the market's labels
    side: Literal["BUY", "SELL"]
    price: Decimal = Field(gt=0, lt=1)  # probability, 0 < p < 1
    size: int = Field(gt=0)  # outcome-token quantity (raw 10^6 units)
    order_type: Literal["GTC", "FOK", "FAK", "GTD"] = "GTC"
    expiration: int = 0  # unix seconds, required if GTD
