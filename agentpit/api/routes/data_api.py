from fastapi import APIRouter

from agentpit.api.deps import AccountServiceDep
from agentpit.datastructures.position_wire import PositionWire

router = APIRouter(tags=["data-api"])


def _csv(value: str | None) -> list[str] | None:
    return [v for v in value.split(",") if v] if value else None


@router.get("/positions", response_model=list[PositionWire])
def get_positions(
    user: str, service: AccountServiceDep, market: str | None = None
) -> list[PositionWire]:
    return service.list_positions(user, _csv(market))


@router.get("/value")
def get_value(user: str, service: AccountServiceDep) -> list[dict]:
    return service.total_value(user)
