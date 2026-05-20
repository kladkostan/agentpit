"""PlaceOrderRequest enforces the 0.1¢ price tick (minimum increment)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentpit.datastructures.place_order_request import PlaceOrderRequest


def _req(price: str) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        market_id=1, outcome="Yes", side="BUY", price=price, size=100
    )


def test_price_snaps_to_tenth_cent_tick():
    """Finer-than-0.1¢ precision is impossible: a 0.0125 submission is snapped
    onto the 0.001 grid rather than resting at sub-tick precision."""
    assert _req("0.0125").price == Decimal("0.012")  # round-half-to-even
    assert _req("0.1239").price == Decimal("0.124")


def test_on_tick_prices_pass_through_unchanged():
    for p in ("0.001", "0.002", "0.123", "0.5", "0.999"):
        assert _req(p).price == Decimal(p)


def test_rejects_when_snapped_out_of_range():
    # Snaps to 0.000 / 1.000 → no longer a valid (0, 1) probability.
    for p in ("0.0004", "0.9997"):
        with pytest.raises(ValidationError):
            _req(p)
