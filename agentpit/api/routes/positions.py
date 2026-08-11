from fastapi import APIRouter
from pydantic import BaseModel

from agentpit.api.deps import CurrentUserDep, PositionServiceDep, SessionDep
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.position_response import PositionResponse
from agentpit.datastructures.redeem_position_response import RedeemPositionResponse
from agentpit.datastructures.split_position_request import (
    MergePositionRequest,
    SplitPositionRequest,
)
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import MarketNotFoundError

router = APIRouter(tags=["positions"])


@router.post("/markets/{market_id}/split_position", response_model=PositionResponse)
def split_position(
    market_id: int,
    payload: SplitPositionRequest,
    user: CurrentUserDep,
    service: PositionServiceDep,
) -> PositionResponse:
    return service.split(user, market_id, payload)


@router.post("/markets/{market_id}/merge_positions", response_model=PositionResponse)
def merge_positions(
    market_id: int,
    payload: MergePositionRequest,
    user: CurrentUserDep,
    service: PositionServiceDep,
) -> PositionResponse:
    return service.merge(user, market_id, payload)


@router.post(
    "/markets/{market_id}/redeem_position", response_model=RedeemPositionResponse
)
def redeem_position(
    market_id: int,
    user: CurrentUserDep,
    service: PositionServiceDep,
) -> RedeemPositionResponse:
    return service.redeem(user, market_id)


class ClaimRequest(BaseModel):
    condition_id: str


@router.post("/positions/claim", response_model=RedeemPositionResponse)
def claim_position(
    payload: ClaimRequest,
    user: CurrentUserDep,
    service: PositionServiceDep,
    db: SessionDep,
) -> RedeemPositionResponse:
    """Claim a won position by its condition id.

    The positions the UI holds carry a `conditionId` and no market id, so the
    existing `/markets/{market_id}/redeem_position` cannot be called from
    there. This resolves the one to the other and delegates; it adds no new
    behaviour of its own.
    """
    with db.read() as conn:
        market = TableRead.read_market_by_condition_id(
            conn, ConditionId(payload.condition_id)
        )
    if market is None:
        raise MarketNotFoundError(0)
    return service.redeem(user, market.market_id)
