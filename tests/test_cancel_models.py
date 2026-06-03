from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
from agentpit.datastructures.cancel_requests import (
    CancelMarketOrdersRequest,
    CancelOrderRequest,
)


def test_cancel_response_defaults_empty():
    r = CancelOrdersResponse()
    assert r.model_dump() == {"canceled": [], "not_canceled": {}}


def test_cancel_response_records_reasons():
    r = CancelOrdersResponse(canceled=["a"], not_canceled={"b": "not found"})
    assert r.canceled == ["a"]
    assert r.not_canceled == {"b": "not found"}


def test_cancel_order_request():
    assert CancelOrderRequest(orderID="0x1").orderID == "0x1"


def test_cancel_market_orders_request_all_optional():
    r = CancelMarketOrdersRequest()
    assert r.market is None and r.asset_id is None
