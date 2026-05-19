from fastapi import APIRouter

from agentpit.api.deps import MarketServiceDep
from agentpit.datastructures.cancel_market_response import CancelMarketResponse
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.list_markets_response import ListMarketsResponse
from agentpit.datastructures.market import Market
from agentpit.datastructures.resolve_market_request import ResolveMarketRequest

router = APIRouter(tags=["markets"])


@router.get("/markets", response_model=ListMarketsResponse)
def list_markets(
    service: MarketServiceDep, limit: int = 100, offset: int = 0
) -> ListMarketsResponse:
    return service.list_markets(limit=limit, offset=offset)


@router.post("/markets", response_model=Market)
def create_market(payload: CreateMarketRequest, service: MarketServiceDep) -> Market:
    return service.create_market(payload)


@router.get("/markets/{market_id}", response_model=Market)
def get_market(market_id: int, service: MarketServiceDep) -> Market:
    return service.get_market(market_id)


@router.post("/markets/{market_id}/activate", response_model=Market)
def activate_market(market_id: int, service: MarketServiceDep) -> Market:
    return service.activate_market(market_id)


@router.post("/markets/{market_id}/close", response_model=Market)
def close_market(market_id: int, service: MarketServiceDep) -> Market:
    return service.close_market(market_id)


@router.post("/markets/{market_id}/cancel", response_model=CancelMarketResponse)
def cancel_market(market_id: int, service: MarketServiceDep) -> CancelMarketResponse:
    return service.cancel_market(market_id)


@router.post("/markets/{market_id}/resolve", response_model=Market)
def resolve_market(
    market_id: int,
    payload: ResolveMarketRequest,
    service: MarketServiceDep,
) -> Market:
    return service.resolve_market(market_id, payload)
