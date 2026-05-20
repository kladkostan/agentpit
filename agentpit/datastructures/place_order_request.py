from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Minimum price increment: 0.1¢ = $0.001. Prices snap to this grid so the book
# can't accumulate sub-tick precision (e.g. 0.0125) — the minimum meaningful
# step is 0.1¢.
_PRICE_TICK = Decimal("0.001")


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

    @field_validator("price")
    @classmethod
    def _snap_to_tick(cls, v: Decimal) -> Decimal:
        """Round the price onto the 0.1¢ tick. Finer precision can't survive —
        it's snapped, not stored. Reject only if snapping leaves (0, 1)."""
        snapped = v.quantize(_PRICE_TICK)
        if snapped <= 0 or snapped >= 1:
            raise ValueError("price must be within (0, 1) on the 0.1¢ tick")
        return snapped
