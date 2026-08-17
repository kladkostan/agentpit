"""A GTD expiration has to be at least three minutes out.

Polymarket rejects anything sooner, and with their one-minute grace that
leaves a shortest usable lifetime of about two minutes. The rule needs the
clock, which is why it is here and not on the model: a model that reads
`time.time()` makes every test that builds one non-deterministic.
"""
import time
from decimal import Decimal

import pytest

from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.domain.exceptions import BusinessRuleError
from agentpit.services.order_service import OrderService


class _Unused:
    """The check runs before anything touches the database or the chain."""

    def __getattr__(self, name):
        raise AssertionError(f"validation should have rejected before {name}")


def _gtd(seconds_out: int) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        token_id="1", side="BUY", price=Decimal("0.5"), size=Decimal("10"),
        order_type="GTD", expiration=int(time.time()) + seconds_out,
    )


def test_an_expiration_under_three_minutes_is_refused():
    svc = OrderService(db=_Unused(), onchain=_Unused())  # type: ignore[arg-type]
    with pytest.raises(BusinessRuleError):
        svc.place_order(_Unused(), _gtd(179))  # type: ignore[arg-type]


def test_an_expiration_in_the_past_is_refused():
    svc = OrderService(db=_Unused(), onchain=_Unused())  # type: ignore[arg-type]
    with pytest.raises(BusinessRuleError):
        svc.place_order(_Unused(), _gtd(-1))  # type: ignore[arg-type]
