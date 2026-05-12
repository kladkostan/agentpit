from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, UsdcServiceDep
from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse

router = APIRouter(tags=["usdc"])


@router.get("/usdc_balance", response_model=GetUsdcBalanceResponse)
def get_usdc_balance(
    user: CurrentUserDep, service: UsdcServiceDep
) -> GetUsdcBalanceResponse:
    return service.get_balance(user)
