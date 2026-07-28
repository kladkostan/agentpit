"""DAL-level tests for the events table and the market<->event binding."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


@pytest.fixture()
def db() -> Any:
    """Fresh in-memory SQLite DB with all tables created."""
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    yield conn
    conn.close()


def _make_market(
    db: sqlite3.Connection,
    *,
    question: str,
    cond_id: str,
    event_id: int | None = None,
    outcome_label: str | None = None,
    icon_url: str | None = None,
):
    """Insert a market via the write path. Returns the created Market."""
    request = CreateMarketRequest(
        question=question,
        description=f"desc for {question}",
        erc1155_tokens=[(f"{cond_id}-yes", "Yes"), (f"{cond_id}-no", "No")],
        slug=question.lower().replace(" ", "-").replace("?", ""),
        condition_id=ConditionId(cond_id),
        state=MarketState.ACTIVE,
        event_id=event_id,
        outcome_label=outcome_label,
        icon_url=icon_url,
    )
    return TableWrite.create_market(db, request, is_polygon_market=False)


def _hex32(seed: str) -> str:
    """Return a 32-byte hex condition_id derived from a short label."""
    payload = seed.encode().hex().ljust(64, "0")[:64]
    return "0x" + payload


# ----- TableWrite.upsert_event ------------------------------------------------


def test_upsert_event_inserts_when_slug_is_new(db):
    event = TableWrite.upsert_event(
        db,
        slug="2026-fifa-world-cup-winner",
        title="2026 FIFA World Cup Winner",
        description="Who lifts the cup?",
        icon_url="https://img/wc.png",
        category="Sports",
        start_date=1_700_000_000,
        end_date=1_750_000_000,
        polymarket_event_id="evt-123",
    )
    assert event.event_id > 0
    assert event.slug == "2026-fifa-world-cup-winner"
    assert event.title == "2026 FIFA World Cup Winner"


def test_upsert_event_updates_when_slug_already_exists(db):
    first = TableWrite.upsert_event(db, slug="wc", title="Old title")
    second = TableWrite.upsert_event(
        db, slug="wc", title="New title", description="updated"
    )

    assert second.event_id == first.event_id
    assert second.title == "New title"

    fetched = TableRead.get_event_by_id(db, first.event_id)
    assert fetched is not None
    assert fetched.title == "New title"
    assert fetched.description == "updated"


# ----- TableRead.get_event_by_* -----------------------------------------------


def test_get_event_by_slug_returns_none_when_missing(db):
    assert TableRead.get_event_by_slug(db, "nope") is None


def test_get_event_by_slug_returns_event(db):
    created = TableWrite.upsert_event(db, slug="wc", title="WC")
    found = TableRead.get_event_by_slug(db, "wc")
    assert found is not None
    assert found.event_id == created.event_id


def test_get_event_by_polymarket_event_id_returns_event(db):
    TableWrite.upsert_event(db, slug="wc", title="WC", polymarket_event_id="pm-evt-1")
    found = TableRead.get_event_by_polymarket_event_id(db, "pm-evt-1")
    assert found is not None
    assert found.slug == "wc"


# ----- Market<->event binding -------------------------------------------------


def test_create_market_persists_event_id_outcome_label_and_icon(db):
    event = TableWrite.upsert_event(db, slug="wc", title="WC")
    market = _make_market(
        db,
        question="Will France win?",
        cond_id=_hex32("france"),
        event_id=event.event_id,
        outcome_label="France",
        icon_url="https://flags/fr.svg",
    )
    assert market.event_id == event.event_id
    assert market.outcome_label == "France"
    assert market.icon_url == "https://flags/fr.svg"

    read = TableRead.read_market(db, market.market_id)
    assert read is not None
    assert read.event_id == event.event_id
    assert read.outcome_label == "France"
    assert read.icon_url == "https://flags/fr.svg"


def test_attach_market_to_event_binds_an_existing_market(db):
    event = TableWrite.upsert_event(db, slug="wc", title="WC")
    market = _make_market(db, question="orphan?", cond_id=_hex32("orphan"))
    assert market.event_id is None

    TableWrite.attach_market_to_event(
        db,
        market_id=market.market_id,
        event_id=event.event_id,
        outcome_label="France",
        icon_url="https://flags/fr.svg",
    )
    read = TableRead.read_market(db, market.market_id)
    assert read is not None
    assert read.event_id == event.event_id
    assert read.outcome_label == "France"
    assert read.icon_url == "https://flags/fr.svg"


def test_attach_market_to_event_preserves_metadata_when_none(db):
    """COALESCE: passing outcome_label=None leaves the existing value alone."""
    event = TableWrite.upsert_event(db, slug="wc", title="WC")
    market = _make_market(
        db,
        question="q",
        cond_id=_hex32("preserve"),
        outcome_label="Original",
        icon_url="https://x/y.svg",
    )
    TableWrite.attach_market_to_event(
        db, market_id=market.market_id, event_id=event.event_id
    )
    read = TableRead.read_market(db, market.market_id)
    assert read is not None
    assert read.outcome_label == "Original"
    assert read.icon_url == "https://x/y.svg"


# ----- listing ----------------------------------------------------------------


def test_list_markets_by_event_id_returns_only_event_members(db):
    event_a = TableWrite.upsert_event(db, slug="a", title="A")
    event_b = TableWrite.upsert_event(db, slug="b", title="B")

    m1 = _make_market(
        db, question="q1", cond_id=_hex32("q1"), event_id=event_a.event_id
    )
    m2 = _make_market(
        db, question="q2", cond_id=_hex32("q2"), event_id=event_a.event_id
    )
    _make_market(db, question="q3", cond_id=_hex32("q3"), event_id=event_b.event_id)
    _make_market(db, question="orphan", cond_id=_hex32("orphan"))

    a_markets = TableRead.list_markets_by_event_id(db, event_a.event_id)
    assert {m.market_id for m in a_markets} == {m1.market_id, m2.market_id}


def test_list_events_with_markets_pairs_each_event_with_its_markets(db):
    event_a = TableWrite.upsert_event(db, slug="a", title="A")
    event_b = TableWrite.upsert_event(db, slug="b", title="B")
    m1 = _make_market(
        db, question="q1", cond_id=_hex32("q1"), event_id=event_a.event_id
    )
    m2 = _make_market(
        db, question="q2", cond_id=_hex32("q2"), event_id=event_a.event_id
    )
    m3 = _make_market(
        db, question="q3", cond_id=_hex32("q3"), event_id=event_b.event_id
    )

    pairs, total = TableRead.list_events_with_markets(db, limit=10, offset=0)
    assert total == 2

    by_slug = {ev.slug: markets for ev, markets in pairs}
    assert {m.market_id for m in by_slug["a"]} == {m1.market_id, m2.market_id}
    assert {m.market_id for m in by_slug["b"]} == {m3.market_id}


def test_list_events_with_markets_orders_events_newest_first(db):
    first = TableWrite.upsert_event(db, slug="first", title="First")
    second = TableWrite.upsert_event(db, slug="second", title="Second")
    pairs, _ = TableRead.list_events_with_markets(db, limit=10, offset=0)
    assert [ev.event_id for ev, _ in pairs] == [second.event_id, first.event_id]


def test_list_events_with_markets_paginates(db):
    for i in range(5):
        TableWrite.upsert_event(db, slug=f"e{i}", title=f"E{i}")
    pairs, total = TableRead.list_events_with_markets(db, limit=2, offset=2)
    assert total == 5
    assert len(pairs) == 2


def test_list_events_with_markets_filters_by_category(db):
    sports = TableWrite.upsert_event(db, slug="sports-e1", title="Sports 1", category="Sports")
    TableWrite.upsert_event(db, slug="sports-e2", title="Sports 2", category="Sports")
    TableWrite.upsert_event(db, slug="crypto-e1", title="Crypto 1", category="Crypto")

    _make_market(
        db,
        question="sports market",
        cond_id=_hex32("sports-market"),
        event_id=sports.event_id,
    )

    pairs, total = TableRead.list_events_with_markets(
        db, limit=10, offset=0, category="Sports"
    )
    assert total == 2
    assert {ev.slug for ev, _ in pairs} == {"sports-e1", "sports-e2"}


def test_list_event_categories_returns_distinct_sorted_non_empty_values(db):
    TableWrite.upsert_event(db, slug="a", title="A", category="Sports")
    TableWrite.upsert_event(db, slug="b", title="B", category="sports")
    TableWrite.upsert_event(db, slug="c", title="C", category="Crypto")
    TableWrite.upsert_event(db, slug="d", title="D", category=None)
    TableWrite.upsert_event(db, slug="e", title="E", category="")

    categories = TableRead.list_event_categories(db)
    assert categories == ["Crypto", "Sports", "sports"]


def test_list_orphan_markets_returns_only_unbound_markets(db):
    event = TableWrite.upsert_event(db, slug="bound", title="Bound")
    bound = _make_market(
        db, question="bound", cond_id=_hex32("bound"), event_id=event.event_id
    )
    orphan = _make_market(db, question="orphan", cond_id=_hex32("orphan"))

    orphans = TableRead.list_orphan_markets(db)
    ids = {m.market_id for m in orphans}
    assert orphan.market_id in ids
    assert bound.market_id not in ids


def test_update_event_category_sets_only_the_category(db):
    event = TableWrite.upsert_event(
        db,
        slug="wc",
        title="World Cup",
        description="Who lifts the cup?",
        icon_url="https://img/wc.png",
        category="Politics",
    )

    TableWrite.update_event_category(db, event_id=event.event_id, category="Sports")

    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None
    assert stored.category == "Sports"
    # Every other column survives untouched.
    assert stored.title == "World Cup"
    assert stored.description == "Who lifts the cup?"
    assert stored.icon_url == "https://img/wc.png"
    assert stored.slug == "wc"


def test_update_event_category_is_idempotent(db):
    event = TableWrite.upsert_event(db, slug="wc", title="WC", category="Sports")

    TableWrite.update_event_category(db, event_id=event.event_id, category="Sports")
    TableWrite.update_event_category(db, event_id=event.event_id, category="Sports")

    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None and stored.category == "Sports"


def test_list_events_with_markets_matches_category_case_insensitively(db):
    """The UI sends its own canonical label; a case drift must not silently
    return zero events."""
    TableWrite.upsert_event(db, slug="t1", title="T1", category="Technology")

    pairs, total = TableRead.list_events_with_markets(
        db, limit=10, offset=0, category="technology"
    )

    assert total == 1
    assert [ev.slug for ev, _ in pairs] == ["t1"]
