from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, PositionServiceDep
from agentpit.datastructures.position_response import PositionResponse
from agentpit.datastructures.redeem_position_response import RedeemPositionResponse
from agentpit.datastructures.split_position_request import (
    MergePositionRequest,
    SplitPositionRequest,
)

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


@router.post("/markets/{market_id}/redeem_position", response_model=RedeemPositionResponse)
def redeem_position(
    market_id: int,
    user: CurrentUserDep,
    service: PositionServiceDep,
) -> RedeemPositionResponse:
    return service.redeem(user, market_id)
