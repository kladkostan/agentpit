import pytest

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import MarketNotFoundError, MarketStateError
from agentpit.polymarket.resolve import resolve_by_market_outcome


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


@pytest.fixture()
def seeded():
    """Fresh in-memory DB (autouse conftest fixture) with one binary market.

    Tokens: "111"->Yes (index 0), "222"->No (index 1).
    """
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("m1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
    return session, market


def test_resolve_by_market_outcome_is_case_insensitive(seeded):
    session, market = seeded
    with session.read() as conn:
        r = resolve_by_market_outcome(conn, market.market_id, "yes")
    assert r.token_id == "111"
    assert r.outcome_index == 0
    assert r.condition_id == market.condition_id.value
    assert r.market.market_id == market.market_id


def test_resolve_by_market_outcome_second_outcome(seeded):
    session, market = seeded
    with session.read() as conn:
        r = resolve_by_market_outcome(conn, market.market_id, "No")
    assert r.token_id == "222"
    assert r.outcome_index == 1


def test_resolve_by_market_outcome_unknown_market_raises():
    session = app.dependency_overrides[get_db_session]()
    with session.read() as conn:
        with pytest.raises(MarketNotFoundError):
            resolve_by_market_outcome(conn, 999, "Yes")


def test_resolve_by_market_outcome_unknown_outcome_raises(seeded):
    session, market = seeded
    with session.read() as conn:
        with pytest.raises(MarketStateError):
            resolve_by_market_outcome(conn, market.market_id, "Maybe")
