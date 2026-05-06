from fastapi import APIRouter

from agentpit.api.deps import PortfolioServiceDep
from agentpit.datastructures.portfolio_response import PortfolioResponse
from agentpit.datastructures.transaction_history_response import TransactionHistoryResponse

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio/{api_key}", response_model=PortfolioResponse)
def get_portfolio(api_key: str, service: PortfolioServiceDep) -> PortfolioResponse:
    return service.get_portfolio(api_key)


@router.get("/markets/history/{api_key}", response_model=TransactionHistoryResponse)
def get_transaction_history(
    api_key: str,
    service: PortfolioServiceDep,
) -> TransactionHistoryResponse:
    return service.get_transaction_history(api_key)
