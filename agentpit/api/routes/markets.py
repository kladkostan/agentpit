from fastapi import APIRouter

from agentpit.api.deps import MarketServiceDep
from agentpit.datastructures.cancel_market_response import CancelMarketResponse
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.gamma_market import GammaMarket
from agentpit.datastructures.market import Market
from agentpit.datastructures.resolve_market_request import ResolveMarketRequest

router = APIRouter(tags=["markets"])


def _csv(value: str | None) -> list[str] | None:
    return [v for v in value.split(",") if v] if value else None


@router.get("/markets", response_model=list[GammaMarket])
def list_markets(
    service: MarketServiceDep,
    limit: int = 100,
    offset: int = 0,
    id: int | None = None,
    slug: str | None = None,
    condition_ids: str | None = None,
    clob_token_ids: str | None = None,
    polymarket_condition_id: str | None = None,
) -> list[GammaMarket]:
    return service.list_markets_gamma(
        limit=limit,
        offset=offset,
        market_id=id,
        slug=slug,
        condition_ids=_csv(condition_ids),
        clob_token_ids=_csv(clob_token_ids),
        polymarket_condition_id=polymarket_condition_id,
    )


@router.post("/markets", response_model=Market)
def create_market(payload: CreateMarketRequest, service: MarketServiceDep) -> Market:
    return service.create_market(payload)


@router.get("/markets/{market_id}", response_model=GammaMarket)
def get_market(market_id: int, service: MarketServiceDep) -> GammaMarket:
    return service.get_market_gamma(market_id)


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
