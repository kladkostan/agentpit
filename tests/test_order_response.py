"""OrderResponse matches Polymarket's postOrder shape (§8.1)."""

import pytest
from pydantic import ValidationError

from agentpit.datastructures.order_response import OrderResponse


def test_minimal_unfilled_order_defaults():
    r = OrderResponse(success=True, orderID="0xabc", status="live")
    d = r.model_dump()
    assert d == {
        "success": True,
        "errorMsg": "",
        "orderID": "0xabc",
        "status": "live",
        "transactionsHashes": [],
        "takingAmount": "",
        "makingAmount": "",
        "tradeIDs": [],
    }


def test_matched_order_carries_hashes_and_amounts():
    r = OrderResponse(
        success=True,
        orderID="0xabc",
        status="matched",
        transactionsHashes=["0xdeadbeef"],
        takingAmount="100",
        makingAmount="36",
        tradeIDs=["t1", "t2"],
    )
    assert r.transactionsHashes == ["0xdeadbeef"]
    assert r.tradeIDs == ["t1", "t2"]


def test_dropped_fields_are_gone():
    # The old agentpit-flavored fields must no longer exist.
    assert "filledSize" not in OrderResponse.model_fields
    assert "remainingSize" not in OrderResponse.model_fields
    assert "avgPrice" not in OrderResponse.model_fields
    assert "txHash" not in OrderResponse.model_fields


def test_empty_order_id_rejected():
    with pytest.raises(ValidationError):
        OrderResponse(success=True, orderID="", status="live")
