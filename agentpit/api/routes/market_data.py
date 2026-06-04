from fastapi import APIRouter

from agentpit.api.deps import OrderServiceDep
from agentpit.datastructures.book_params import BookParams
from agentpit.datastructures.orderbook_summary import OrderBookSummary

router = APIRouter(tags=["market-data"])


@router.get("/book", response_model=OrderBookSummary)
def get_book(token_id: str, service: OrderServiceDep) -> OrderBookSummary:
    return service.get_book(token_id)


@router.post("/books", response_model=list[OrderBookSummary])
def get_books(
    params: list[BookParams], service: OrderServiceDep
) -> list[OrderBookSummary]:
    return service.get_books([p.token_id for p in params])


@router.get("/prices-history")
def get_prices_history(
    market: str,
    service: OrderServiceDep,
    startTs: int | None = None,
    endTs: int | None = None,
    interval: str = "1d",
    fidelity: int = 0,
) -> dict:
    return service.get_prices_history(
        market, start_ts=startTs, end_ts=endTs, interval=interval, fidelity=fidelity
    )
