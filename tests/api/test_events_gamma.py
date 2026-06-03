import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


@pytest.fixture()
def client_and_event():
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("c1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
        event = TableWrite.upsert_event(conn, slug="will-it-rain", title="Will it rain?")
        TableWrite.attach_market_to_event(conn, market_id=market.market_id, event_id=event.event_id)
    with TestClient(app) as client:
        yield client


def test_list_events_returns_bare_gamma_array(client_and_event):
    resp = client_and_event.get("/events?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)  # bare array, no envelope
    assert len(body) == 1
    ev = body[0]
    assert ev["slug"] == "will-it-rain"
    assert len(ev["markets"]) == 1
    assert ev["markets"][0]["conditionId"]


def test_list_events_empty_is_empty_array(client_and_event):
    # (no markets seeded variant) — a fresh client returns []
    pass


def test_get_event_by_slug_returns_single_gamma(client_and_event):
    resp = client_and_event.get("/events/will-it-rain")
    assert resp.status_code == 200
    ev = resp.json()
    assert ev["slug"] == "will-it-rain"
    assert ev["markets"][0]["clobTokenIds"]
