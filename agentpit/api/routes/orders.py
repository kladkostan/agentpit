from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, OrderServiceDep
from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
from agentpit.datastructures.cancel_requests import (
    CancelMarketOrdersRequest,
    CancelOrderRequest,
)
from agentpit.datastructures.order_response import OrderResponse
from agentpit.datastructures.place_order_request import PlaceOrderRequest

router = APIRouter(tags=["orders"])


@router.post("/order", response_model=OrderResponse)
def place_order(
    payload: PlaceOrderRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> OrderResponse:
    return service.place_order(user, payload)


@router.delete("/order", response_model=CancelOrdersResponse)
def cancel_order(
    payload: CancelOrderRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_orders(user, [payload.orderID])


@router.delete("/orders", response_model=CancelOrdersResponse)
def cancel_orders(
    order_ids: list[str],
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_orders(user, order_ids)


@router.delete("/cancel-all", response_model=CancelOrdersResponse)
def cancel_all(
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_all(user)


@router.delete("/cancel-market-orders", response_model=CancelOrdersResponse)
def cancel_market_orders(
    payload: CancelMarketOrdersRequest,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> CancelOrdersResponse:
    return service.cancel_market_orders(user, payload.market, payload.asset_id)


@router.get("/orders/mine")
def list_my_orders(
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> dict:
    return {"orders": service.list_live_orders(user)}


@router.get("/orderbook/{market_id}/{outcome}")
def get_orderbook(
    market_id: int,
    outcome: str,
    service: OrderServiceDep,
) -> dict:
    return service.get_orderbook(market_id, outcome)


@router.get("/sparkline/{market_id}/{outcome}")
def get_sparkline(
    market_id: int,
    outcome: str,
    service: OrderServiceDep,
    window_hours: int = 24,
) -> dict:
    return service.get_sparkline(market_id, outcome, window_hours=window_hours)
