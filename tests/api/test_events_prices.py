"""End-to-end: a market with a live local book surfaces book-derived prices
(outcomePrices/bestBid/bestAsk/spread) through the Gamma event serialization,
instead of the neutral 0.5 placeholder."""

import uuid

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite
from agentpit.services.event_service import EventService


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _insert_order(conn, *, token, side, price, remaining, status="live"):
    conn.execute(
        "INSERT INTO orders (API_KEY, PRICE, POST_ONLY, ORDER_TYPE, SALT, MAKER, "
        "TAKER, SIGNER, TOKEN_ID, MAKER_AMOUNT, TAKER_AMOUNT, EXPIRATION, NONCE, "
        "FEE_RATE_BPS, SIDE, SIGNATURE_TYPE, SIGNATURE, ORDER_JSON, STATUS, "
        "REMAINING_AMOUNT, CREATED_AT, ORDER_ID) VALUES "
        "('m',%s,0,'GTC','0','0x0','0x0','0x0',%s,0,0,0,0,0,%s,'EIP712','sig',"
        "'{}',%s,%s,0,%s)",
        (price, token, side, status, remaining, uuid.uuid4().hex),
    )


def test_list_events_gamma_reports_book_derived_prices():
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("p1", "Yes"), ("p2", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("c1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
        event = TableWrite.upsert_event(
            conn, slug="will-it-rain", title="Will it rain?"
        )
        TableWrite.attach_market_to_event(
            conn, market_id=market.market_id, event_id=event.event_id
        )
        # YES book 0.14 / 0.15 -> mid 0.145; NO has no book -> complement 0.855.
        _insert_order(conn, token="p1", side="BUY", price=140_000, remaining=5)
        _insert_order(conn, token="p1", side="SELL", price=150_000, remaining=5)

    events = EventService(session).list_events_gamma(limit=10, offset=0)
    m = events[0].markets[0]
    assert m.outcomePrices == '["0.145","0.855"]'
    assert m.bestBid == 0.14
    assert m.bestAsk == 0.15
    assert m.spread == 0.01


def test_list_events_gamma_keeps_placeholder_without_book():
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it snow?",
        description="d",
        erc1155_tokens=[("q1", "Yes"), ("q2", "No")],
        slug="will-it-snow",
        condition_id=ConditionId(_hex32("c2")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
        event = TableWrite.upsert_event(
            conn, slug="will-it-snow", title="Will it snow?"
        )
        TableWrite.attach_market_to_event(
            conn, market_id=market.market_id, event_id=event.event_id
        )

    events = EventService(session).list_events_gamma(limit=10, offset=0)
    m = events[0].markets[0]
    assert m.outcomePrices == '["0.5","0.5"]'  # no book -> neutral fallback
    assert m.bestBid == 0.0 and m.bestAsk == 0.0
