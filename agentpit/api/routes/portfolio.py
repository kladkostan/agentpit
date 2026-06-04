from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, PortfolioServiceDep
from agentpit.datastructures.portfolio_response import PortfolioResponse

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(
    user: CurrentUserDep,
    service: PortfolioServiceDep,
    market_id: int | None = None,
) -> PortfolioResponse:
    return service.get_portfolio(user, market_id=market_id)
