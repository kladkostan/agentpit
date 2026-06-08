"""TDD specs for EventService.

The service wraps DB reads/writes and is the single entry-point for routes.
It also owns the "every market belongs to an event" invariant via the
auto-wrap helper used at startup.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import EventNotFoundError
from agentpit.services.event_service import EventService
from tests.db_helpers import fresh_test_db


@pytest.fixture()
def db_session() -> Any:
    session = fresh_test_db()
    yield session
    session.close()


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed_market(
    session,
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


# ----- get_event_by_slug ------------------------------------------------------


def test_get_event_by_slug_raises_when_missing(db_session):
    service = EventService(db_session)
    with pytest.raises(EventNotFoundError):
        service.get_event_by_slug("nope")


def test_get_event_by_slug_returns_event_with_markets(db_session):
    with db_session.write() as conn:
        event = TableWrite.upsert_event(conn, slug="wc", title="WC")
    m_france = _seed_market(
        db_session,
        question="france?",
        cond_id=_hex32("france"),
        event_id=event.event_id,
        outcome_label="France",
    )
    m_spain = _seed_market(
        db_session,
        question="spain?",
        cond_id=_hex32("spain"),
        event_id=event.event_id,
        outcome_label="Spain",
    )

    service = EventService(db_session)
    detail = service.get_event_by_slug("wc")
    assert detail.event.slug == "wc"
    assert {m.market_id for m in detail.markets} == {
        m_france.market_id,
        m_spain.market_id,
    }


# ----- list_events ------------------------------------------------------------


def test_list_events_returns_paginated_event_summaries(db_session):
    with db_session.write() as conn:
        for i in range(3):
            TableWrite.upsert_event(conn, slug=f"e{i}", title=f"E{i}")

    service = EventService(db_session)
    resp = service.list_events(limit=2, offset=0)
    assert resp.total == 3
    assert resp.limit == 2
    assert resp.offset == 0
    assert len(resp.events) == 2


def test_list_events_includes_member_markets_per_event(db_session):
    with db_session.write() as conn:
        event = TableWrite.upsert_event(conn, slug="wc", title="WC")
    _seed_market(
        db_session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=event.event_id,
        outcome_label="France",
    )
    _seed_market(
        db_session,
        question="spain?",
        cond_id=_hex32("es"),
        event_id=event.event_id,
        outcome_label="Spain",
    )

    service = EventService(db_session)
    resp = service.list_events(limit=10, offset=0)
    assert len(resp.events) == 1
    summary = resp.events[0]
    assert summary.event.slug == "wc"
    assert len(summary.markets) == 2


# ----- ensure_singleton_events_for_orphans ------------------------------------


def test_ensure_singleton_events_wraps_each_orphan_market(db_session):
    market = _seed_market(db_session, question="solo?", cond_id=_hex32("solo"))
    assert market.event_id is None

    service = EventService(db_session)
    wrapped = service.ensure_singleton_events_for_orphans()

    assert wrapped == 1
    with db_session.read() as conn:
        rebound = TableRead.read_market(conn, market.market_id)
        assert rebound is not None
        assert rebound.event_id is not None
        # Event slug should derive from the market slug so it is stable.
        ev = TableRead.get_event_by_id(conn, rebound.event_id)
        assert ev is not None
        assert ev.slug == market.slug
        assert ev.title == market.question


def test_ensure_singleton_events_is_idempotent(db_session):
    _seed_market(db_session, question="solo?", cond_id=_hex32("solo"))
    service = EventService(db_session)
    service.ensure_singleton_events_for_orphans()
    second_pass = service.ensure_singleton_events_for_orphans()
    assert second_pass == 0


def test_ensure_singleton_events_leaves_already_bound_markets_alone(db_session):
    with db_session.write() as conn:
        event = TableWrite.upsert_event(conn, slug="wc", title="WC")
    bound = _seed_market(
        db_session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=event.event_id,
        outcome_label="France",
    )

    service = EventService(db_session)
    service.ensure_singleton_events_for_orphans()
    with db_session.read() as conn:
        re = TableRead.read_market(conn, bound.market_id)
        assert re is not None and re.event_id == event.event_id


# ----- wrap_market_in_singleton_event_if_needed -------------------------------


def test_wrap_market_in_singleton_creates_event_for_orphan(db_session):
    market = _seed_market(db_session, question="solo?", cond_id=_hex32("solo"))
    assert market.event_id is None

    service = EventService(db_session)
    service.wrap_market_in_singleton_event_if_needed(market.market_id)

    with db_session.read() as conn:
        re = TableRead.read_market(conn, market.market_id)
        assert re is not None and re.event_id is not None
        ev = TableRead.get_event_by_id(conn, re.event_id)
        assert ev is not None and ev.slug == market.slug


def test_wrap_market_in_singleton_noop_when_already_bound(db_session):
    with db_session.write() as conn:
        existing = TableWrite.upsert_event(conn, slug="wc", title="WC")
    market = _seed_market(
        db_session,
        question="france?",
        cond_id=_hex32("fr"),
        event_id=existing.event_id,
        outcome_label="France",
    )

    service = EventService(db_session)
    service.wrap_market_in_singleton_event_if_needed(market.market_id)
    with db_session.read() as conn:
        re = TableRead.read_market(conn, market.market_id)
        assert re is not None and re.event_id == existing.event_id  # untouched


# ----- MarketService integration (locally-created markets are never orphans) --


def test_market_service_create_market_attaches_singleton_event(db_session):
    """POST /markets must produce a market bound to a singleton event
    immediately. Without this, the market is invisible on the home page
    (which lists events) until the next process restart.
    """
    from agentpit.services.market_service import MarketService

    # condition_id is set => on-chain prep is skipped, no admin needed.
    payload = CreateMarketRequest(
        question="will solo win?",
        description="solo market",
        erc1155_tokens=[("tok-y", "Yes"), ("tok-n", "No")],
        slug="will-solo-win",
        condition_id=ConditionId(_hex32("solo")),
        state=MarketState.ACTIVE,
    )
    service = MarketService(db_session, onchain=None)  # type: ignore[arg-type]
    market = service.create_market(payload)

    assert market.event_id is not None, "newly-created market must be bound"
    with db_session.read() as conn:
        ev = TableRead.get_event_by_id(conn, market.event_id)
        assert ev is not None and ev.slug == "will-solo-win"
