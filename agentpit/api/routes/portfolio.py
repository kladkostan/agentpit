from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep, PortfolioServiceDep
from agentpit.datastructures.portfolio_response import PortfolioResponse
from agentpit.datastructures.transaction_history_response import TransactionHistoryResponse

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(user: CurrentUserDep, service: PortfolioServiceDep) -> PortfolioResponse:
    return service.get_portfolio(user)


@router.get("/transactions", response_model=TransactionHistoryResponse)
def get_transaction_history(
    user: CurrentUserDep,
    service: PortfolioServiceDep,
) -> TransactionHistoryResponse:
    return service.get_transaction_history(user)
