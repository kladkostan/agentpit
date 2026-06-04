from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, UsdcServiceDep
from agentpit.datastructures.balance_allowance import BalanceAllowanceResponse

router = APIRouter(tags=["balance"])


@router.get("/balance-allowance", response_model=BalanceAllowanceResponse)
def get_balance_allowance(
    user: CurrentUserDep,
    service: UsdcServiceDep,
    asset_type: str = "COLLATERAL",
    token_id: str | None = None,
    signature_type: int | None = None,   # accepted, ignored (§2)
) -> BalanceAllowanceResponse:
    return service.get_balance_allowance(user, asset_type, token_id)
