from agentpit.datastructures.event_with_markets import (
    EventWithMarkets,
    ListEventsResponse,
)
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import EventNotFoundError, InvalidPaginationError


class EventService:
    def __init__(self, db: DbSession):
        self._db = db

    def list_events(self, limit: int, offset: int) -> ListEventsResponse:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            pairs, total = TableRead.list_events_with_markets(
                conn, limit=limit, offset=offset
            )
        events = [
            EventWithMarkets(event=event, markets=markets) for event, markets in pairs
        ]
        return ListEventsResponse(
            events=events, total=total, limit=limit, offset=offset
        )

    def get_event_by_slug(self, slug: str) -> EventWithMarkets:
        with self._db.read() as conn:
            event = TableRead.get_event_by_slug(conn, slug)
            if event is None:
                raise EventNotFoundError(slug)
            markets = TableRead.list_markets_by_event_id(conn, event.event_id)
        return EventWithMarkets(event=event, markets=markets)

    def ensure_singleton_events_for_orphans(self) -> int:
        """Wrap every market with no event in a singleton event.

        Idempotent: orphans become bound after the first pass, so subsequent
        passes return 0. Uses the market's own slug as the event slug and the
        market's question as the event title to give the home-page card a
        stable identity.
        """
        wrapped = 0
        with self._db.write() as conn:
            orphans = TableRead.list_orphan_markets(conn)
            for market in orphans:
                _bind_singleton(conn, market)
                wrapped += 1
        return wrapped

    def wrap_market_in_singleton_event_if_needed(self, market_id: int) -> None:
        """Enforce the "every market belongs to an event" invariant for a
        single market — e.g. after `POST /markets` creates a local market
        with no event_id. No-op if the market is already bound.
        """
        with self._db.write() as conn:
            market = TableRead.read_market(conn, market_id)
            if market is None or market.event_id is not None:
                return
            _bind_singleton(conn, market)


def _bind_singleton(conn, market) -> None:
    event = TableWrite.upsert_event(
        conn,
        slug=market.slug,
        title=market.question,
        description=market.description,
        start_date=market.start_date,
        end_date=market.end_date,
    )
    TableWrite.attach_market_to_event(
        conn, market_id=market.market_id, event_id=event.event_id
    )
