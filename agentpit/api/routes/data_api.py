from fastapi import APIRouter

from agentpit.api.deps import AccountServiceDep
from agentpit.datastructures.activity_wire import ActivityWire
from agentpit.datastructures.position_wire import PositionWire

router = APIRouter(tags=["data-api"])


def _csv(value: str | None) -> list[str] | None:
    return [v for v in value.split(",") if v] if value else None


@router.get("/positions", response_model=list[PositionWire])
def get_positions(
    user: str, service: AccountServiceDep, market: str | None = None
) -> list[PositionWire]:
    return service.list_positions(user, _csv(market))


@router.get("/closed-positions", response_model=list[PositionWire])
def get_closed_positions(
    user: str, service: AccountServiceDep
) -> list[PositionWire]:
    """Resolved/cancelled positions (reconstructed from trade history), with
    realized payout + PnL — the Active /positions list drops them once redeemed."""
    return service.list_closed_positions(user)


@router.get("/value")
def get_value(user: str, service: AccountServiceDep) -> list[dict]:
    return service.total_value(user)


@router.get("/activity", response_model=list[ActivityWire])
def get_activity(
    user: str,
    service: AccountServiceDep,
    type: str | None = None,
    market: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ActivityWire]:
    return service.list_activity(
        user, type_filter=_csv(type), market=_csv(market), limit=limit, offset=offset
    )
