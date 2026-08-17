"""An expiration and an order type have to agree with each other.

These two rules are pure — they compare two fields and need no clock — so
they live on the model, next to the fields. The three-minute floor does need
a clock and lives in the service; see `tests/services/test_order_expiry.py`.
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentpit.datastructures.place_order_request import PlaceOrderRequest


def _req(**over):
    base = dict(token_id="1", side="BUY", price=Decimal("0.5"), size=Decimal("10"))
    base.update(over)
    return PlaceOrderRequest(**base)


def test_a_gtd_order_without_an_expiration_is_refused():
    # "Good till date" with no date is not "good forever", it is a caller
    # who forgot a field, and answering it with an immortal order is the
    # one reading of it nobody wants.
    with pytest.raises(ValidationError):
        _req(order_type="GTD", expiration=0)


def test_an_expiration_on_a_non_gtd_order_is_refused():
    # Silently dropping it is worse: the caller finds out when the order
    # fails to disappear, long after they stopped watching.
    with pytest.raises(ValidationError):
        _req(order_type="GTC", expiration=1_800_000_000)


def test_a_gtd_order_with_an_expiration_is_accepted():
    req = _req(order_type="GTD", expiration=1_800_000_000)
    assert req.expiration == 1_800_000_000


def test_the_default_order_is_gtc_and_never_expires():
    req = _req()
    assert (req.order_type, req.expiration) == ("GTC", 0)
