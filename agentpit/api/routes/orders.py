from fastapi import APIRouter, HTTPException, status

from agentpit.api.deps import CurrentUserDep, OrderServiceDep
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


@router.delete("/orders/{order_id}")
def cancel_order(
    order_id: str,
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> dict:
    cancelled = service.cancel_order(user, order_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found, not yours, or already settled",
        )
    return {"order_id": order_id, "status": "cancelled"}


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
