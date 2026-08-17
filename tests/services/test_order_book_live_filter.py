"""OrderService.get_book must not surface an order whose GTD expiration has
already passed.

`tests/test_live_order_guard.py` proves no query spells the predicate out by
hand, and `tests/db/test_live_order_predicate.py` proves `TableRead.LIVE_ORDER`
itself excludes an expired row -- but neither proves `get_book` actually uses
that fragment. Both of those tests build their SQL from the constant, so
deleting `AND {TableRead.LIVE_ORDER}` from `get_book` in
`agentpit/services/order_service.py` would leave every one of them green.

This test goes through the service instead of raw SQL, so it is the one that
would actually fail if that fragment were removed from `get_book`.
"""
import time

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market import Market
from agentpit.db.table_write import TableWrite
from agentpit.services.order_service import OrderService
from tests.db_helpers import fresh_test_db


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(session) -> Market:
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[(_hex32("yes"), "Yes"), (_hex32("no"), "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("cond")),
    )
    with session.write() as conn:
        return TableWrite.create_market(conn, req, is_polygon_market=False)


def _seed_resting_order(
    session, *, order_id: str, token_id: str, price_micro_usd: int, expiration: int
) -> None:
    with session.write() as conn:
        conn.execute(
            "INSERT INTO orders (ORDER_ID, TOKEN_ID, SIDE, PRICE, STATUS, "
            "REMAINING_AMOUNT, EXPIRATION, CREATED_AT, API_KEY) "
            "VALUES (%s, %s, 'BUY', %s, 'live', 1000000, %s, %s, 'k')",
            (order_id, token_id, price_micro_usd, expiration, int(time.time())),
        )


def test_get_book_excludes_an_expired_order_and_keeps_a_live_one():
    session = fresh_test_db()
    try:
        market = _seed_market(session)
        yes_token = market.erc1155_tokens[0][0]
        now = int(time.time())
        _seed_resting_order(
            session,
            order_id="o-expired",
            token_id=yes_token,
            price_micro_usd=400_000,
            expiration=now - 3600,  # a GTD that expired an hour ago
        )
        _seed_resting_order(
            session,
            order_id="o-live",
            token_id=yes_token,
            price_micro_usd=450_000,
            expiration=0,  # GTC, never expires
        )

        svc = OrderService(db=session, onchain=None)  # type: ignore[arg-type]
        book = svc.get_book(yes_token)

        prices = [level.price for level in book.bids]
        assert "0.45" in prices  # the live order is present
        assert "0.4" not in prices  # the expired order is absent
    finally:
        session.close()
