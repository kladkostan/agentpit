"""HTTP-level tests for the /events endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_db_session
from agentpit.api.main import app as _app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite


@pytest.fixture()
def client_and_db():
    """A TestClient plus the live DB session it routes to."""
    session = _app.dependency_overrides[get_db_session]()
    with TestClient(_app) as client:
        yield client, session


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(
    session: Any,
    *,
    question: str,
    cond_id: str,
    event_id: int | None = None,
    outcome_label: str | None = None,
):
    req = CreateMarketRequest(
        question=question,
        description=f"d-{question}",
        erc1155_tokens=[(f"{cond_id}-y", "Yes"), (f"{cond_id}-n", "No")],
        slug=question.lower().replace(" ", "-").replace("?", ""),
        condition_id=ConditionId(cond_id),
        state=MarketState.ACTIVE,
        event_id=event_id,
        outcome_label=outcome_label,
    )
    with session.write() as conn:
        return TableWrite.create_market(conn, req, is_polygon_market=False)


# ----- GET /events ------------------------------------------------------------


def test_list_events_returns_empty_when_no_events(client_and_db):
    client, _ = client_and_db
    resp = client.get("/events?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"events": [], "total": 0, "limit": 10, "offset": 0}


def test_list_events_returns_events_with_their_markets(client_and_db):
    client, session = client_and_db
    with session.write() as conn:
        event = TableWrite.upsert_event(conn, slug="wc", title="WC")
    m1 = _seed_market(
        session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=event.event_id,
        outcome_label="France",
    )
    m2 = _seed_market(
        session,
        question="spain?",
        cond_id=_hex32("es"),
        event_id=event.event_id,
        outcome_label="Spain",
    )

    resp = client.get("/events?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    summary = body["events"][0]
    assert summary["event"]["slug"] == "wc"
    assert {m["market_id"] for m in summary["markets"]} == {m1.market_id, m2.market_id}


def test_list_events_rejects_bad_pagination(client_and_db):
    client, _ = client_and_db
    resp = client.get("/events?limit=0")
    assert resp.status_code == 400


def test_list_events_can_filter_by_category(client_and_db):
    client, session = client_and_db
    with session.write() as conn:
        sports = TableWrite.upsert_event(
            conn, slug="wc", title="World Cup", category="Sports"
        )
        TableWrite.upsert_event(conn, slug="btc", title="BTC", category="Crypto")
    _seed_market(
        session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=sports.event_id,
        outcome_label="France",
    )

    resp = client.get("/events?limit=10&offset=0&category=Sports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    assert body["events"][0]["event"]["slug"] == "wc"


def test_list_event_categories_returns_distinct_categories(client_and_db):
    client, session = client_and_db
    with session.write() as conn:
        TableWrite.upsert_event(conn, slug="wc", title="World Cup", category="Sports")
        TableWrite.upsert_event(conn, slug="btc", title="BTC", category="Crypto")
        TableWrite.upsert_event(conn, slug="election", title="Election", category="Sports")

    resp = client.get("/events/categories")
    assert resp.status_code == 200
    assert resp.json() == {"categories": ["Crypto", "Sports"]}


# ----- GET /events/{slug} -----------------------------------------------------


def test_get_event_by_slug_returns_404_when_missing(client_and_db):
    client, _ = client_and_db
    resp = client.get("/events/nope")
    assert resp.status_code == 404


def test_get_event_by_slug_returns_event_and_markets(client_and_db):
    client, session = client_and_db
    with session.write() as conn:
        event = TableWrite.upsert_event(
            conn,
            slug="wc",
            title="2026 FIFA World Cup Winner",
            description="Who lifts the cup?",
            icon_url="https://i/wc.svg",
            category="Sports",
        )
    m1 = _seed_market(
        session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=event.event_id,
        outcome_label="France",
    )

    resp = client.get("/events/wc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["event"]["slug"] == "wc"
    assert body["event"]["title"] == "2026 FIFA World Cup Winner"
    assert body["event"]["icon_url"] == "https://i/wc.svg"
    assert [m["market_id"] for m in body["markets"]] == [m1.market_id]
    assert body["markets"][0]["outcome_label"] == "France"
