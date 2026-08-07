"""DAL-level tests for market_tags: schema, replace semantics, normalisation."""

from __future__ import annotations

from typing import Any

import pytest

from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_create import TableCreate
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
