"""DAL-level tests for market_tags: schema, replace semantics, normalisation."""

from __future__ import annotations

from typing import Any

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def _hex32(seed: str) -> str:
    payload = seed.encode().hex().ljust(64, "0")[:64]
    return "0x" + payload


def _make_market(db, *, question: str, cond_id: str, event_id: int | None = None):
    request = CreateMarketRequest(
        question=question,
        description=f"desc for {question}",
        erc1155_tokens=[(f"{cond_id}-yes", "Yes"), (f"{cond_id}-no", "No")],
        slug=question.lower().replace(" ", "-").replace("?", ""),
        condition_id=ConditionId(cond_id),
        state=MarketState.ACTIVE,
        event_id=event_id,
    )
    return TableWrite.create_market(db, request, is_polygon_market=False)


def _slugs(db, market_id: int) -> list[str]:
    rows = db.execute(
        "SELECT SLUG FROM market_tags WHERE MARKET_ID = %s ORDER BY SLUG",
        (market_id,),
    ).fetchall()
    return [r["SLUG"] for r in rows]


def test_create_market_tags_table_is_idempotent(db):
    # create_all_tables already ran in the fixture; a second call must not raise.
    TableCreate.create_market_tags_table(db)
    TableCreate.create_market_tags_table(db)
    assert _slugs(db, 1) == []


def test_replace_market_tags_inserts(db):
    m = _make_market(db, question="Q1?", cond_id=_hex32("m1"))
    TableWrite.replace_market_tags(
        db, market_id=m.market_id, tags=[("politics", "Politics"), ("iran", "Iran")]
    )
    assert _slugs(db, m.market_id) == ["iran", "politics"]


def test_replace_market_tags_replaces_rather_than_accumulates(db):
    """A tag removed upstream must disappear locally.

    This is the whole reason tags live on the market and not on the event: an
    event-level union can only ever grow.
    """
    m = _make_market(db, question="Q2?", cond_id=_hex32("m2"))
    TableWrite.replace_market_tags(
        db, market_id=m.market_id, tags=[("politics", "Politics"), ("iran", "Iran")]
    )
    TableWrite.replace_market_tags(
        db, market_id=m.market_id, tags=[("politics", "Politics")]
    )
    assert _slugs(db, m.market_id) == ["politics"]


def test_replace_market_tags_with_empty_list_clears(db):
    m = _make_market(db, question="Q3?", cond_id=_hex32("m3"))
    TableWrite.replace_market_tags(db, market_id=m.market_id, tags=[("iran", "Iran")])
    TableWrite.replace_market_tags(db, market_id=m.market_id, tags=[])
    assert _slugs(db, m.market_id) == []


def test_replace_market_tags_dedupes_within_one_call(db):
    """Two upstream entries normalising to the same slug must not violate the
    primary key — psycopg would abort the whole statement."""
    m = _make_market(db, question="Q4?", cond_id=_hex32("m4"))
    TableWrite.replace_market_tags(
        db, market_id=m.market_id, tags=[("1h", "1H"), ("1h", "1h")]
    )
    assert _slugs(db, m.market_id) == ["1h"]


def test_replace_market_tags_scopes_to_one_market(db):
    a = _make_market(db, question="Qa?", cond_id=_hex32("ma"))
    b = _make_market(db, question="Qb?", cond_id=_hex32("mb"))
    TableWrite.replace_market_tags(db, market_id=a.market_id, tags=[("iran", "Iran")])
    TableWrite.replace_market_tags(db, market_id=b.market_id, tags=[("oil", "Oil")])
    TableWrite.replace_market_tags(db, market_id=a.market_id, tags=[])
    assert _slugs(db, a.market_id) == []
    assert _slugs(db, b.market_id) == ["oil"]


def test_replace_market_tags_keeps_the_label(db):
    m = _make_market(db, question="Q5?", cond_id=_hex32("m5"))
    TableWrite.replace_market_tags(
        db, market_id=m.market_id, tags=[("pop-culture", "Culture")]
    )
    row = db.execute(
        "SELECT LABEL FROM market_tags WHERE MARKET_ID = %s", (m.market_id,)
    ).fetchone()
    assert row["LABEL"] == "Culture"


# ----- TableRead.list_tag_nav / list_tag_facets -------------------------------


def _event_with_tagged_markets(db, *, slug: str, tags_per_market: list[list[str]]):
    """Create one event whose markets carry the given tag slugs.

    Returns the event. Labels are derived from the slug so assertions can check
    the label plumbing without a second parameter.
    """
    event = TableWrite.upsert_event(db, slug=slug, title=slug.replace("-", " ").title())
    for i, slugs in enumerate(tags_per_market):
        market = _make_market(
            db,
            question=f"{slug} m{i}?",
            cond_id=_hex32(f"{slug}{i}"),
            event_id=event.event_id,
        )
        TableWrite.replace_market_tags(
            db,
            market_id=market.market_id,
            tags=[(s, s.replace("-", " ").title()) for s in slugs],
        )
    return event


def test_list_tag_nav_counts_events_not_markets(db):
    """Two markets of one event both tagged `politics` is ONE politics event."""
    _event_with_tagged_markets(db, slug="e1", tags_per_market=[["politics"], ["politics"]])
    rows = TableRead.list_tag_nav(db, slugs=["politics"], min_events=1)
    assert rows == [("politics", "Politics", 1)]


def test_list_tag_nav_unions_tags_across_an_events_markets(db):
    """An event's tag set is the union over its markets — market A carries
    `politics`, market B carries `iran`, the event has both."""
    _event_with_tagged_markets(db, slug="e2", tags_per_market=[["politics"], ["iran"]])
    rows = dict((s, c) for s, _, c in TableRead.list_tag_nav(
        db, slugs=["politics", "iran"], min_events=1
    ))
    assert rows == {"politics": 1, "iran": 1}


def test_list_tag_nav_applies_the_threshold(db):
    _event_with_tagged_markets(db, slug="e3", tags_per_market=[["politics"]])
    _event_with_tagged_markets(db, slug="e4", tags_per_market=[["politics"]])
    _event_with_tagged_markets(db, slug="e5", tags_per_market=[["science"]])
    got = {s for s, _, _ in TableRead.list_tag_nav(
        db, slugs=["politics", "science"], min_events=2
    )}
    assert got == {"politics"}


def test_list_tag_nav_ignores_slugs_not_asked_for(db):
    _event_with_tagged_markets(db, slug="e6", tags_per_market=[["politics", "iran"]])
    got = {s for s, _, _ in TableRead.list_tag_nav(db, slugs=["politics"], min_events=1)}
    assert got == {"politics"}


def test_list_tag_nav_skips_markets_with_no_event(db):
    market = _make_market(db, question="orphan?", cond_id=_hex32("orph"))
    TableWrite.replace_market_tags(
        db, market_id=market.market_id, tags=[("politics", "Politics")]
    )
    assert TableRead.list_tag_nav(db, slugs=["politics"], min_events=1) == []


def test_list_tag_facets_orders_by_event_count_descending(db):
    for i in range(3):
        _event_with_tagged_markets(db, slug=f"p{i}", tags_per_market=[["politics", "elections"]])
    _event_with_tagged_markets(db, slug="p3", tags_per_market=[["politics", "iran"]])
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="politics",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=1.0,
    )
    assert [(s, c) for s, _, c in rows] == [("elections", 3), ("iran", 1)]


def test_list_tag_facets_finds_cross_market_co_occurrence(db):
    """Co-occurrence is at EVENT level, not market level: `politics` on one
    market and `trump` on a *different* market of the same event must still
    pair up as a facet. A regression that joined `parent_events` on
    MARKET_ID instead of EVENT_ID would miss this and pass every other facet
    test, since they all put parent and facet tags on the same market."""
    _event_with_tagged_markets(db, slug="r1", tags_per_market=[["politics"], ["trump"]])
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="politics",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=1.0,
    )
    assert [(s, c) for s, _, c in rows] == [("trump", 1)]


def test_list_tag_facets_excludes_the_parent_itself(db):
    _event_with_tagged_markets(db, slug="q1", tags_per_market=[["politics", "iran"]])
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="politics",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=1.0,
    )
    assert [s for s, _, _ in rows] == ["iran"]


def test_list_tag_facets_excludes_blocked_and_deprecated_slugs(db):
    _event_with_tagged_markets(
        db,
        slug="q2",
        tags_per_market=[["politics", "recurring", "deprec-us-election", "iran"]],
    )
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="politics",
        blocked=frozenset({"recurring"}),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=1.0,
    )
    assert [s for s, _, _ in rows] == ["iran"]


def test_list_tag_facets_drops_a_facet_above_the_coverage_ceiling(db):
    """`games` sits on 832 of 895 Sports events — it is the parent under
    another name and tells a reader nothing."""
    for i in range(10):
        _event_with_tagged_markets(db, slug=f"s{i}", tags_per_market=[["sports", "games"]])
    _event_with_tagged_markets(db, slug="s-tennis", tags_per_market=[["sports", "tennis"]])
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="sports",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=0.9,
    )
    # games = 10/11 = 0.909 > 0.9 → dropped. tennis = 1/11 → kept.
    assert [s for s, _, _ in rows] == ["tennis"]


def test_list_tag_facets_caps_the_list(db):
    _event_with_tagged_markets(
        db, slug="q3", tags_per_market=[["politics"] + [f"t{i}" for i in range(30)]]
    )
    rows = TableRead.list_tag_facets(
        db,
        parent_slug="politics",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=5,
        max_coverage=1.0,
    )
    assert len(rows) == 5


def test_list_tag_facets_returns_empty_for_an_unknown_parent(db):
    assert TableRead.list_tag_facets(
        db,
        parent_slug="nope",
        blocked=frozenset(),
        deprecated_prefix="deprec-",
        limit=20,
        max_coverage=0.9,
    ) == []
