from agentpit.datastructures.cancel_market_response import CancelMarketResponse
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.list_markets_response import ListMarketsResponse
from agentpit.datastructures.market import Market
from agentpit.datastructures.resolve_market_request import ResolveMarketRequest
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import (
    InvalidPaginationError,
    MarketNotFoundError,
    MarketStateError,
)


class MarketService:
    def __init__(self, db: DbSession):
        self._db = db

    def list_markets(self, limit: int, offset: int) -> ListMarketsResponse:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            markets, total = TableRead.list_markets(conn, limit=limit, offset=offset)
        return ListMarketsResponse(markets=markets, total=total, limit=limit, offset=offset)

    def get_market(self, market_id: int) -> Market:
        with self._db.read() as conn:
            market = TableRead.read_market(conn, market_id)
        if market is None:
            raise MarketNotFoundError(market_id)
        return market

    def create_market(self, payload: CreateMarketRequest) -> Market:
        with self._db.write() as conn:
            return TableWrite.create_market(conn, payload, False)

    def activate_market(self, market_id: int) -> Market:
        with self._db.write() as conn:
            try:
                return TableWrite.activate_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e

    def close_market(self, market_id: int) -> Market:
        with self._db.write() as conn:
            try:
                return TableWrite.close_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e

    def cancel_market(self, market_id: int) -> CancelMarketResponse:
        with self._db.write() as conn:
            try:
                market, refunds_processed = TableWrite.cancel_market(conn, market_id)
            except ValueError as e:
                raise MarketStateError(str(e)) from e
        return CancelMarketResponse(
            market_id=market.market_id,
            message="Market cancelled successfully",
            refunds_processed=refunds_processed,
            market=market,
        )

    def resolve_market(self, market_id: int, payload: ResolveMarketRequest) -> Market:
        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                raise MarketNotFoundError(market_id)
            try:
                return TableWrite.resolve_market(
                    conn,
                    market_id=market_id,
                    winning_outcome_index=payload.winning_outcome_index,
                )
            except ValueError as e:
                raise MarketStateError(str(e)) from e
