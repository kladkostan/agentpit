# Server-Side Event Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every sort option on the markets page order the whole catalogue on the server, instead of re-shuffling whichever pages the reader has happened to scroll past.

**Architecture:** `/events` orders by `VOLUME_24HR DESC` and nothing else, while the UI re-sorts the accumulated pages client-side. Only the default sort agrees with the server, so the other five silently rank a partial list — measured on production, 5 of 20 events on page 2 belong above page 1 under "Total Volume", and 16 of 20 under "Liquidity". This adds the two upstream fields those sorts actually need (`liquidity`, `competitive`), threads a `sort` parameter through the DAL, service, route and cache, and deletes the client-side sort entirely.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres, pydantic; React 18 + TypeScript + Vite, TanStack Query, vitest.

**Design context:** agreed in conversation, no separate spec document. The two new fields are Polymarket's own, taken verbatim from Gamma's event payload:

- `liquidity` — dollars resting in the order book. Event-level, e.g. Fed Decision $1,976,644 vs a LoL match at $118.
- `competitive` — a score in [0, 1] for how contested the odds are. Fed Decision 0.985 (49% vs 48%); a 97/3 market scores low.

They are orthogonal: two LoL matches shared `competitive = 0.862` while their liquidity differed by four orders of magnitude. Today the UI computes BOTH from `markets.length` — the number of outcomes — which is neither, and makes the "Liquidity" and "Competitive" menu entries literally identical sorts.

## Global Constraints

- Branch is `mvp`. Work directly in the repo; no worktree.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env` before pytest** — `tests/conftest.py` uses `os.environ.setdefault`, so a sourced `.env` defeats every default and causes live-sync flakes.
- UI verification, run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. All four must pass.
- `ui/` vitest runs in the **node** environment; `@testing-library/react` is **not installed**. Component rendering in a test is impossible — only pure-logic `.ts` tests.
- `tsconfig` sets `exactOptionalPropertyTypes`: an optional property that can be absent must be typed `foo?: T | undefined`.
- **The default ordering must not change.** `volume24h` stays the default and keeps emitting exactly `ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC`. Two existing tests pin it: `tests/test_event_volume.py::test_events_ordered_by_volume_desc_nulls_last` and `tests/db/test_events_dal.py::test_list_events_with_markets_orders_events_newest_first`.
- **Every ORDER BY ends with `EVENT_ID DESC`.** Without a unique tiebreak, two events with equal sort values can swap between `LIMIT/OFFSET` pages, so an event is shown twice and another never at all.
- **Every ORDER BY on a nullable column uses `NULLS LAST`** for descending and `NULLS LAST` for ascending too — an event with no captured value belongs at the bottom of the list, never at the top of "Ending Soon".
- The `sort` value is caller-supplied: an unrecognised value falls back to the default rather than reaching SQL. **Never interpolate the caller's string into the query.**
- All DB rows are dict-style and case-insensitive (`ci_dict_row`): `row["SLUG"]` and `row["slug"]` both work.
- Every DDL statement must be idempotent (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — `create_all_tables` runs on every app construction against the live database.
- `TableCreate`, `TableRead`, `TableWrite` are classes of `@staticmethod`s; intra-class calls go through the class name.
- Do not remove `?category=`, `?tag=`, `?subtag=`, or `/events/categories`. This change is additive.

---

## File Structure

**Create:**

| Path | Responsibility |
| --- | --- |
| `agentpit/datastructures/event_sort.py` | The `EventSort` enum and its ORDER BY fragments. Pure — no DB, no HTTP. |
| `scripts/backfill_event_metrics.py` | One-off backfill of LIQUIDITY/COMPETITIVE from Gamma for events outside the sync window. |
| `tests/db/test_event_sort.py` | Tasks 1 and 3. |
| `tests/api/test_events_sort.py` | Task 5. |

**Modify:**

| Path | Change |
| --- | --- |
| `agentpit/db/table_create.py` | two idempotent `ADD COLUMN`s + two indexes |
| `agentpit/datastructures/event.py` | `liquidity`, `competitive` fields |
| `agentpit/db/table_read.py` | `_EVENT_COLS`, `_row_to_event`, `list_events_with_markets(sort=…)` |
| `agentpit/db/table_write.py` | `update_event_metrics` |
| `agentpit/polymarket/polymarket_sync.py` | capture both fields in `_extract_event_metadata` and write them |
| `agentpit/polymarket/gamma.py` | `to_gamma_event` emits both |
| `agentpit/datastructures/gamma_market.py` | `GammaEvent.liquidity`, `GammaEvent.competitive` |
| `agentpit/services/event_service.py` | `sort` on `list_events` / `list_events_gamma` |
| `agentpit/api/routes/events.py` | `?sort=` param + cache key |
| `ui/src/types/gamma.ts`, `ui/src/types/event.ts` | the two new fields |
| `ui/src/api/events.ts` | `sort` param, threaded into the query key |
| `ui/src/pages/MarketsPage.tsx` | pass the sort; delete the client-side sort block |

---

## Task 1: The sort enum and its ORDER BY fragments

**Files:**
- Create: `agentpit/datastructures/event_sort.py`
- Test: `tests/db/test_event_sort.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EventSort` (a `str` Enum with members `VOLUME_24H`, `TOTAL_VOLUME`, `LIQUIDITY`, `COMPETITIVE`, `NEWEST`, `ENDING_SOON`, whose values are the wire strings `"volume24h"`, `"totalVolume"`, `"liquidity"`, `"competitive"`, `"newest"`, `"endingSoon"`); `EventSort.DEFAULT`; `EventSort.parse(value: object) -> EventSort`; `EventSort.order_by(self) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_event_sort.py`:

```python
"""The sort enum is the only place a caller-supplied string becomes SQL."""

from __future__ import annotations

import pytest

from agentpit.datastructures.event_sort import EventSort


def test_wire_values_match_what_the_ui_sends():
    assert [s.value for s in EventSort] == [
        "volume24h",
        "totalVolume",
        "liquidity",
        "competitive",
        "newest",
        "endingSoon",
    ]


def test_the_default_is_24h_volume():
    # The home page has ranked on this since before sorting existed; changing
    # it would silently reorder everyone's first screen.
    assert EventSort.DEFAULT is EventSort.VOLUME_24H


def test_parse_accepts_a_known_wire_value():
    assert EventSort.parse("liquidity") is EventSort.LIQUIDITY
    assert EventSort.parse("endingSoon") is EventSort.ENDING_SOON


def test_parse_falls_back_rather_than_raising():
    """`sort` is caller-supplied. A 500 on `?sort=nonsense` would let anyone
    take the listing down, and an exception here would reach the home page."""
    for junk in ["nonsense", "", "  ", None, 7, "DROP TABLE events"]:
        assert EventSort.parse(junk) is EventSort.DEFAULT


def test_parse_is_case_and_whitespace_tolerant():
    assert EventSort.parse(" Liquidity ") is EventSort.LIQUIDITY
    assert EventSort.parse("ENDINGSOON") is EventSort.ENDING_SOON


def test_the_default_order_by_is_unchanged():
    """Pinned verbatim: two existing tests depend on this exact clause."""
    assert (
        EventSort.VOLUME_24H.order_by()
        == "VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC"
    )


def test_every_order_by_ends_with_the_unique_tiebreak():
    """Without it, two events with equal sort values can swap between LIMIT
    pages — one gets shown twice and another never at all."""
    for sort in EventSort:
        assert sort.order_by().endswith("EVENT_ID DESC"), sort


def test_every_order_by_puts_missing_values_last():
    """An event we never captured a figure for belongs at the bottom, not at
    the top of "Ending Soon"."""
    for sort in EventSort:
        head = sort.order_by().split(",")[0]
        assert "NULLS LAST" in head, sort


def test_ending_soon_is_the_only_ascending_sort():
    assert EventSort.ENDING_SOON.order_by().startswith("END_DATE ASC")
    for sort in EventSort:
        if sort is not EventSort.ENDING_SOON:
            assert " ASC" not in sort.order_by().split(",")[0], sort


def test_each_sort_uses_its_own_column():
    columns = {sort: sort.order_by().split()[0] for sort in EventSort}
    assert columns[EventSort.VOLUME_24H] == "VOLUME_24HR"
    assert columns[EventSort.TOTAL_VOLUME] == "VOLUME"
    assert columns[EventSort.LIQUIDITY] == "LIQUIDITY"
    assert columns[EventSort.COMPETITIVE] == "COMPETITIVE"
    assert columns[EventSort.NEWEST] == "START_DATE"
    assert columns[EventSort.ENDING_SOON] == "END_DATE"
    # Liquidity and Competitive were the same sort before this existed.
    assert len(set(columns.values())) == len(EventSort)


def test_order_by_contains_no_caller_supplied_text():
    """The enum is the whole allow-list. Nothing a caller sends reaches SQL."""
    assert EventSort.parse("VOLUME_24HR; DROP TABLE events").order_by() == (
        EventSort.DEFAULT.order_by()
    )


@pytest.mark.parametrize("sort", list(EventSort))
def test_order_by_is_a_bare_clause(sort: EventSort):
    """Callers splice this after the words ORDER BY; a leading keyword or a
    trailing semicolon would break the query they build."""
    clause = sort.order_by()
    assert not clause.upper().startswith("ORDER BY")
    assert ";" not in clause
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.datastructures.event_sort'`

- [ ] **Step 3: Write the implementation**

Create `agentpit/datastructures/event_sort.py`:

```python
"""How the events listing can be ordered, and the SQL each choice means.

This enum is the entire allow-list between a query string and an ORDER BY.
`sort` arrives from the caller, so nothing here interpolates it: `parse`
either returns a member or the default, and only members can produce SQL.

Every clause ends in `EVENT_ID DESC`. Without a unique tiebreak two events
with equal sort values can swap places between LIMIT/OFFSET pages, and the
reader sees one of them twice and the other never — the exact bug this whole
change exists to fix, reintroduced one level down.
"""

from __future__ import annotations

from enum import Enum


class EventSort(str, Enum):
    """Values are the wire strings the UI sends."""

    VOLUME_24H = "volume24h"
    TOTAL_VOLUME = "totalVolume"
    LIQUIDITY = "liquidity"
    COMPETITIVE = "competitive"
    NEWEST = "newest"
    ENDING_SOON = "endingSoon"

    @classmethod
    def parse(cls, value: object) -> "EventSort":
        """A known wire value, else the default.

        Never raises: `sort` is caller-supplied, and a 500 on `?sort=nonsense`
        would let anyone take the home page down.
        """
        if not isinstance(value, str):
            return cls.DEFAULT
        wanted = value.strip().lower()
        for member in cls:
            if member.value.lower() == wanted:
                return member
        return cls.DEFAULT

    def order_by(self) -> str:
        """The clause to splice after the words ORDER BY.

        `NULLS LAST` on every leading column: an event we never captured a
        figure for belongs at the bottom of the list, never at the top of
        "Ending Soon".
        """
        return _ORDER_BY[self]


#: Assigned after the class body — an Enum treats a plain class attribute as
#: another member, so DEFAULT cannot be declared inside it.
EventSort.DEFAULT = EventSort.VOLUME_24H  # type: ignore[attr-defined]

_ORDER_BY: "dict[EventSort, str]" = {
    # Unchanged, and pinned by tests/test_event_volume.py: this is what the
    # home page has ranked on since before sorting was a choice.
    EventSort.VOLUME_24H: "VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC",
    EventSort.TOTAL_VOLUME: "VOLUME DESC NULLS LAST, EVENT_ID DESC",
    EventSort.LIQUIDITY: "LIQUIDITY DESC NULLS LAST, EVENT_ID DESC",
    EventSort.COMPETITIVE: "COMPETITIVE DESC NULLS LAST, EVENT_ID DESC",
    EventSort.NEWEST: "START_DATE DESC NULLS LAST, EVENT_ID DESC",
    EventSort.ENDING_SOON: "END_DATE ASC NULLS LAST, EVENT_ID DESC",
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q`
Expected: PASS, 16 tests (11 plus the 6-way parametrize, minus one — count is informational, all must pass).

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS — this task adds a leaf module nothing imports yet.

- [ ] **Step 6: Commit**

```bash
git add agentpit/datastructures/event_sort.py tests/db/test_event_sort.py
git commit -m "feat(events): the sort enum and its ORDER BY fragments"
```

---

## Task 2: Capture liquidity and competitive from upstream

**Files:**
- Modify: `agentpit/db/table_create.py` (in `create_events_table`)
- Modify: `agentpit/datastructures/event.py`
- Modify: `agentpit/db/table_read.py` (`_EVENT_COLS`, `_row_to_event`)
- Modify: `agentpit/db/table_write.py` (add a method beside `update_event_volume`)
- Modify: `agentpit/polymarket/polymarket_sync.py` (`_extract_event_metadata`, `bind_market_to_upstream_event`)
- Test: `tests/db/test_event_sort.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `events.LIQUIDITY` and `events.COMPETITIVE`, both `DOUBLE PRECISION`, nullable.
  - `Event.liquidity: float | None` and `Event.competitive: float | None`.
  - `TableWrite.update_event_metrics(db, event_id: int, liquidity: float | None, competitive: float | None) -> None`.
  - `_extract_event_metadata` returns two more keys: `"liquidity"` and `"competitive"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/db/test_event_sort.py`:

```python
# ----- capturing the two upstream metrics -------------------------------------

from typing import Any  # noqa: E402

from agentpit.db.table_read import TableRead  # noqa: E402
from agentpit.db.table_write import TableWrite  # noqa: E402
from agentpit.polymarket.polymarket_sync import _extract_event_metadata  # noqa: E402
from tests.db_helpers import fresh_test_conn  # noqa: E402


@pytest.fixture()
def db() -> Any:
    conn = fresh_test_conn()
    yield conn
    conn.close()


def test_a_fresh_event_has_no_metrics_yet(db):
    event = TableWrite.upsert_event(db, slug="m1", title="M1")
    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None
    assert stored.liquidity is None
    assert stored.competitive is None


def test_update_event_metrics_stores_both(db):
    event = TableWrite.upsert_event(db, slug="m2", title="M2")
    TableWrite.update_event_metrics(db, event.event_id, 1976643.77, 0.9846)
    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None
    assert abs(stored.liquidity - 1976643.77) < 1e-6
    assert abs(stored.competitive - 0.9846) < 1e-9


def test_update_event_metrics_skips_each_figure_independently(db):
    """A degraded pass carrying only one figure must not blank the other —
    the same discipline update_event_volume already follows."""
    event = TableWrite.upsert_event(db, slug="m3", title="M3")
    TableWrite.update_event_metrics(db, event.event_id, 500.0, 0.5)
    TableWrite.update_event_metrics(db, event.event_id, 900.0, None)
    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None
    assert abs(stored.liquidity - 900.0) < 1e-6
    assert abs(stored.competitive - 0.5) < 1e-9, "competitive was clobbered"


def test_update_event_metrics_with_both_none_is_a_no_op(db):
    event = TableWrite.upsert_event(db, slug="m4", title="M4")
    TableWrite.update_event_metrics(db, event.event_id, 7.0, 0.7)
    TableWrite.update_event_metrics(db, event.event_id, None, None)
    stored = TableRead.get_event_by_id(db, event.event_id)
    assert stored is not None
    assert abs(stored.liquidity - 7.0) < 1e-6


def _pm_market(**event_fields) -> dict:
    """An upstream market payload wrapping one event."""
    return {
        "tags": [],
        "events": [
            {"id": "9", "slug": "e", "title": "E", **event_fields},
        ],
    }


def test_extract_event_metadata_reads_both_metrics():
    meta = _extract_event_metadata(
        _pm_market(liquidity=1976643.77453, competitive=0.9846153846153846)
    )
    assert meta is not None
    assert abs(meta["liquidity"] - 1976643.77453) < 1e-6
    assert abs(meta["competitive"] - 0.9846153846153846) < 1e-12


def test_extract_event_metadata_reads_them_from_strings():
    """Gamma stringifies numbers on some payloads — volume already arrives
    that way, so the same coercion has to cover these."""
    meta = _extract_event_metadata(_pm_market(liquidity="123.5", competitive="0.42"))
    assert meta is not None
    assert abs(meta["liquidity"] - 123.5) < 1e-6
    assert abs(meta["competitive"] - 0.42) < 1e-9


def test_extract_event_metadata_leaves_absent_metrics_none():
    """None means "upstream said nothing, keep what is stored" — the same
    signal update_event_metrics acts on."""
    meta = _extract_event_metadata(_pm_market())
    assert meta is not None
    assert meta["liquidity"] is None
    assert meta["competitive"] is None


def test_extract_event_metadata_survives_unparseable_metrics():
    """A raise here would permanently skip this market on every future pass."""
    meta = _extract_event_metadata(_pm_market(liquidity="n/a", competitive={}))
    assert meta is not None
    assert meta["liquidity"] is None
    assert meta["competitive"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q -k metric`
Expected: FAIL — `AttributeError: type object 'TableWrite' has no attribute 'update_event_metrics'`

- [ ] **Step 3: Add the columns**

In `agentpit/db/table_create.py`, inside `create_events_table`, immediately after the existing `VOLUME` migration:

```python
        # Order-book depth in dollars, straight from Gamma's event payload.
        # Drives the "Liquidity" sort, which until now ranked on the number of
        # outcomes — a different quantity entirely.
        conn.execute(
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS LIQUIDITY DOUBLE PRECISION"
        )
        # How contested the odds are, 0..1. A 50/50 market scores near 1, a
        # 97/3 market near 0. Independent of liquidity: two matches can share a
        # competitive score while their books differ by four orders of magnitude.
        conn.execute(
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS COMPETITIVE DOUBLE PRECISION"
        )
```

and, beside the existing `idx_events_volume_24hr`:

```python
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_liquidity ON events(LIQUIDITY)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_competitive ON events(COMPETITIVE)"
        )
```

- [ ] **Step 4: Carry the fields through the Event model and the reader**

In `agentpit/datastructures/event.py`, add two fields beside `volume`, both defaulting to `None` so every existing constructor call keeps working:

```python
    # Order-book depth in dollars, captured at sync time. Drives the Liquidity
    # sort. None when never synced from upstream.
    liquidity: Optional[float] = None
    # How contested the odds are, 0..1 — a 50/50 market scores near 1. Captured
    # at the same time; independent of liquidity. None when never synced.
    competitive: Optional[float] = None
```

`Event` is a pydantic `BaseModel` and the file spells its nullable fields
`Optional[float] = None`; match that rather than introducing `float | None`
into a file that uses neither.

In `agentpit/db/table_read.py`, extend `_EVENT_COLS`:

```python
    _EVENT_COLS = (
        "EVENT_ID, SLUG, TITLE, DESCRIPTION, ICON_URL, CATEGORY, "
        "START_DATE, END_DATE, POLYMARKET_EVENT_ID, VOLUME_24HR, VOLUME, "
        "LIQUIDITY, COMPETITIVE"
    )
```

and add the two fields to `_row_to_event`, after `volume=row["VOLUME"],`:

```python
            liquidity=row["LIQUIDITY"],
            competitive=row["COMPETITIVE"],
```

- [ ] **Step 5: Add the writer**

In `agentpit/db/table_write.py`, immediately after `update_event_volume`:

```python
    @staticmethod
    def update_event_metrics(
        db: psycopg.Connection,
        event_id: int,
        liquidity: float | None,
        competitive: float | None,
    ) -> None:
        """Refresh an event's captured order-book depth and contest score.

        Each figure is skipped independently when None, exactly as
        `update_event_volume` treats the volumes: a payload carrying only one
        of the two must not blank the other, and a pass where upstream sent
        neither must not blank both. Called on every bind pass.
        """
        sets = []
        params: list[object] = []
        if liquidity is not None:
            sets.append("LIQUIDITY = %s")
            params.append(liquidity)
        if competitive is not None:
            sets.append("COMPETITIVE = %s")
            params.append(competitive)
        if not sets:
            return
        params.append(event_id)
        db.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE EVENT_ID = %s",
            tuple(params),
        )
```

- [ ] **Step 6: Capture the fields in the sync**

In `agentpit/polymarket/polymarket_sync.py`, inside `_extract_event_metadata`, beside the existing `volume24hr`/`volume` reads:

```python
    liquidity = raw.get("liquidity")
    competitive = raw.get("competitive")
```

and add two entries to the returned dict, beside `"volume"`:

```python
        "liquidity": _as_optional_float(liquidity),
        "competitive": _as_optional_float(competitive),
```

**Do NOT reuse `_as_float` here.** Read it: it returns `0.0` for anything
unparseable, which is the right call for a volume (a missing volume really is
zero) and the wrong one for these two. `0.0` would mean "this event has no
order book and its odds are maximally lopsided" — a claim upstream never made
— and `update_event_metrics` skips only on `None`, so the fabricated zero
would be written and would then sort the event to the bottom of two menus
forever. Add a sibling beside `_as_float`:

```python
def _as_optional_float(value: object) -> float | None:
    """A number, or None when upstream sent nothing usable.

    Distinct from `_as_float`, which answers 0.0: for a volume that is honest,
    but a liquidity of 0.0 asserts an empty order book and a competitive of
    0.0 asserts a settled market. None is the signal `update_event_metrics`
    skips on, so an unparseable payload leaves whatever was already stored.
    """
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
```

Then, in `bind_market_to_upstream_event`, immediately after the existing `TableWrite.update_event_volume(...)` call:

```python
    TableWrite.update_event_metrics(
        db, event.event_id, meta["liquidity"], meta["competitive"]
    )
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `Event` gained two defaulted fields, so every existing constructor still type-checks and runs.

- [ ] **Step 9: Commit**

```bash
git add agentpit/db/table_create.py agentpit/datastructures/event.py \
        agentpit/db/table_read.py agentpit/db/table_write.py \
        agentpit/polymarket/polymarket_sync.py tests/db/test_event_sort.py
git commit -m "feat(events): capture upstream liquidity and competitive"
```

---

## Task 3: Order the listing query

**Files:**
- Modify: `agentpit/db/table_read.py` (`list_events_with_markets`)
- Test: `tests/db/test_event_sort.py` (append)

**Interfaces:**
- Consumes: `EventSort` (Task 1); `Event.liquidity` / `Event.competitive` and their columns (Task 2).
- Produces: `TableRead.list_events_with_markets(db, limit=100, offset=0, category=None, tag=None, subtags=None, sort=None)` where `sort: EventSort | None`; `None` means `EventSort.DEFAULT`. Return type unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/db/test_event_sort.py`:

```python
# ----- ordering the listing ---------------------------------------------------


def _event(db, slug, **cols):
    """An event with whatever metrics the test cares about."""
    ev = TableWrite.upsert_event(
        db,
        slug=slug,
        title=slug.upper(),
        start_date=cols.pop("start_date", None),
        end_date=cols.pop("end_date", None),
    )
    if "volume_24hr" in cols or "volume" in cols:
        TableWrite.update_event_volume(
            db, ev.event_id, cols.pop("volume_24hr", None), cols.pop("volume", None)
        )
    if "liquidity" in cols or "competitive" in cols:
        TableWrite.update_event_metrics(
            db, ev.event_id, cols.pop("liquidity", None), cols.pop("competitive", None)
        )
    assert not cols, f"unused: {cols}"
    return ev


def _slugs(db, sort):
    pairs, _total = TableRead.list_events_with_markets(db, limit=50, offset=0, sort=sort)
    return [ev.slug for ev, _ in pairs]


def test_default_sort_is_unchanged_when_none_is_passed(db):
    _event(db, "lo", volume_24hr=1.0)
    _event(db, "hi", volume_24hr=99.0)
    assert _slugs(db, None) == ["hi", "lo"]


def test_total_volume_ranks_on_the_all_time_figure(db):
    # Deliberately opposed to the 24h figure, so a sort that ignored the
    # parameter would fail rather than coincidentally pass.
    _event(db, "a", volume_24hr=100.0, volume=1.0)
    _event(db, "b", volume_24hr=1.0, volume=100.0)
    assert _slugs(db, EventSort.TOTAL_VOLUME) == ["b", "a"]
    assert _slugs(db, EventSort.VOLUME_24H) == ["a", "b"]


def test_liquidity_and_competitive_are_different_sorts(db):
    """They ranked identically before this change, because both were computed
    from the number of outcomes."""
    _event(db, "deep", liquidity=1_000_000.0, competitive=0.10)
    _event(db, "contested", liquidity=100.0, competitive=0.99)
    assert _slugs(db, EventSort.LIQUIDITY) == ["deep", "contested"]
    assert _slugs(db, EventSort.COMPETITIVE) == ["contested", "deep"]


def test_newest_ranks_on_start_date_descending(db):
    _event(db, "old", start_date=1_000)
    _event(db, "new", start_date=9_000)
    assert _slugs(db, EventSort.NEWEST) == ["new", "old"]


def test_ending_soon_ranks_on_end_date_ascending(db):
    _event(db, "later", end_date=9_000)
    _event(db, "sooner", end_date=1_000)
    assert _slugs(db, EventSort.ENDING_SOON) == ["sooner", "later"]


def test_missing_values_sort_last_even_when_ascending(db):
    """The trap: NULL sorts FIRST by default under ASC in Postgres, which
    would put every never-captured event at the top of "Ending Soon"."""
    _event(db, "dated", end_date=5_000)
    _event(db, "undated")
    assert _slugs(db, EventSort.ENDING_SOON) == ["dated", "undated"]


def test_missing_values_sort_last_when_descending(db):
    _event(db, "measured", liquidity=5.0)
    _event(db, "unmeasured")
    assert _slugs(db, EventSort.LIQUIDITY) == ["measured", "unmeasured"]


def test_ties_break_on_event_id_so_pages_do_not_overlap(db):
    """Equal sort values with no unique tiebreak let two events swap between
    LIMIT/OFFSET pages — one shown twice, the other never."""
    first = _event(db, "t1", liquidity=42.0)
    second = _event(db, "t2", liquidity=42.0)
    assert _slugs(db, EventSort.LIQUIDITY) == ["t2", "t1"]
    assert second.event_id > first.event_id

    page1, _ = TableRead.list_events_with_markets(
        db, limit=1, offset=0, sort=EventSort.LIQUIDITY
    )
    page2, _ = TableRead.list_events_with_markets(
        db, limit=1, offset=1, sort=EventSort.LIQUIDITY
    )
    assert [e.slug for e, _ in page1] + [e.slug for e, _ in page2] == ["t2", "t1"]


def test_sort_composes_with_a_tag_filter(db):
    """Filtering and ordering are independent: the sort must apply to the
    filtered set, not to the whole table."""
    keep = _event(db, "keep", liquidity=1.0)
    _event(db, "drop", liquidity=999.0)
    market = _make_market(db, question="q1?", cond_id=_hex32("s1"), event_id=keep.event_id)
    TableWrite.replace_market_tags(db, market_id=market.market_id, tags=[("politics", "Politics")])

    pairs, total = TableRead.list_events_with_markets(
        db, limit=50, offset=0, tag="politics", sort=EventSort.LIQUIDITY
    )
    assert [ev.slug for ev, _ in pairs] == ["keep"]
    assert total == 1
```

Add to that file's imports: `from agentpit.datastructures.condition_id import ConditionId`, `from agentpit.datastructures.create_market_request import CreateMarketRequest`, `from agentpit.datastructures.market_state import MarketState`, and copy the `_make_market` and `_hex32` helpers verbatim from `tests/db/test_events_dal.py` (lines 25–52) — they are module-private there, not importable.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q -k "sort or ranks or ties or missing"`
Expected: FAIL — `TypeError: list_events_with_markets() got an unexpected keyword argument 'sort'`

- [ ] **Step 3: Write the implementation**

In `agentpit/db/table_read.py`, add the parameter to `list_events_with_markets`'s signature, after `subtags`:

```python
        sort: "EventSort | None" = None,
```

Add the import at the top of the file, beside the other datastructure imports:

```python
from agentpit.datastructures.event_sort import EventSort
```

Replace the SELECT so it takes its clause from the enum. The current line is:

```python
            f"SELECT {TableRead._EVENT_COLS} FROM events{where} "
            "ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC LIMIT %s OFFSET %s",
```

It becomes:

```python
            f"SELECT {TableRead._EVENT_COLS} FROM events{where} "
            f"ORDER BY {(sort or EventSort.DEFAULT).order_by()} "
            "LIMIT %s OFFSET %s",
```

The f-string is safe here and only here: `order_by()` returns one of six
constants held in the enum, and `sort` is already an `EventSort` by the time
it arrives — the parsing of caller text happens at the route boundary.

Extend the method's docstring with one paragraph:

```
        ``sort`` chooses the ordering; ``None`` means
        ``EventSort.DEFAULT`` — 24h volume, the ranking the home page has used
        since before sorting was a choice. Every clause ends in ``EVENT_ID
        DESC`` so equal values cannot swap between pages, and puts missing
        values last so a never-captured event never leads the list.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_event_sort.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. In particular `tests/test_event_volume.py` and `tests/db/test_events_dal.py` still pin the default ordering, and neither passes `sort`.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_event_sort.py
git commit -m "feat(events): order the listing query by the requested sort"
```

---

## Task 4: Serve the two metrics over the API

**Files:**
- Modify: `agentpit/datastructures/gamma_market.py` (`GammaEvent`)
- Modify: `agentpit/polymarket/gamma.py` (`to_gamma_event`)
- Test: `tests/api/test_events_sort.py` (create)

**Interfaces:**
- Consumes: `Event.liquidity` / `Event.competitive` (Task 2).
- Produces: `GammaEvent.liquidity: str` and `GammaEvent.competitive: str`, both defaulting to `"0"`, stringified like the existing `volume` fields.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_events_sort.py`:

```python
"""GET /events: the two upstream metrics on the wire, and the ?sort= param."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentpit.api.main import app
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _seed(events: "dict[str, dict]") -> None:
    """`{slug: {volume_24hr, volume, liquidity, competitive, start_date, end_date}}`."""
    conn = fresh_test_conn()
    try:
        for slug, cols in events.items():
            ev = TableWrite.upsert_event(
                conn,
                slug=slug,
                title=slug.upper(),
                start_date=cols.get("start_date"),
                end_date=cols.get("end_date"),
            )
            TableWrite.update_event_volume(
                conn, ev.event_id, cols.get("volume_24hr"), cols.get("volume")
            )
            TableWrite.update_event_metrics(
                conn, ev.event_id, cols.get("liquidity"), cols.get("competitive")
            )
    finally:
        conn.close()


def test_the_wire_carries_both_metrics(client):
    _seed({"a": {"liquidity": 1976643.77, "competitive": 0.9846}})
    body = client.get("/events?limit=10").json()
    assert body[0]["liquidity"] == "1976643.77"
    assert body[0]["competitive"] == "0.9846"


def test_an_uncaptured_metric_serialises_as_zero_not_null(client):
    """Gamma's own convention, and the one `volume` already follows — the UI
    parses these with the same helper."""
    _seed({"a": {}})
    body = client.get("/events?limit=10").json()
    assert body[0]["liquidity"] == "0"
    assert body[0]["competitive"] == "0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_events_sort.py -q`
Expected: FAIL — `KeyError: 'liquidity'`

- [ ] **Step 3: Write the implementation**

In `agentpit/datastructures/gamma_market.py`, add two fields to `GammaEvent` beside `volume`:

```python
    #: Order-book depth, stringified (Gamma's wire convention). "0" when the
    #: event was never synced from upstream.
    liquidity: str = "0"
    #: How contested the odds are, 0..1, stringified. "0" when never synced.
    competitive: str = "0"
```

In `agentpit/polymarket/gamma.py`, add two arguments to the `GammaEvent(...)` call inside `to_gamma_event`, beside the volumes:

```python
        liquidity=str(event.liquidity if event.liquidity is not None else 0),
        competitive=str(event.competitive if event.competitive is not None else 0),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_events_sort.py -q`
Expected: PASS, 2 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `tests/api/test_events_gamma.py` asserts the Gamma shape; two new defaulted fields are additive.

- [ ] **Step 6: Commit**

```bash
git add agentpit/datastructures/gamma_market.py agentpit/polymarket/gamma.py \
        tests/api/test_events_sort.py
git commit -m "feat(events): serve liquidity and competitive on the wire"
```

---

## Task 5: `GET /events?sort=`

**Files:**
- Modify: `agentpit/services/event_service.py` (`list_events`, `list_events_gamma`)
- Modify: `agentpit/api/routes/events.py` (cache key, `_list_events_cached`, the route)
- Test: `tests/api/test_events_sort.py` (append)

**Interfaces:**
- Consumes: `EventSort.parse` (Task 1); `list_events_with_markets(..., sort=…)` (Task 3).
- Produces: `GET /events?sort=<wire value>`; `EventService.list_events_gamma(limit, offset, category=None, tag=None, subtags=None, sort=None)` taking `sort: EventSort | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_events_sort.py`:

```python
# ----- the ?sort= parameter ---------------------------------------------------


def _slugs(client, query: str) -> "list[str]":
    return [e["slug"] for e in client.get(f"/events?limit=10&{query}").json()]


def test_sort_defaults_to_24h_volume(client):
    _seed({"lo": {"volume_24hr": 1.0}, "hi": {"volume_24hr": 99.0}})
    assert _slugs(client, "") == ["hi", "lo"]


def test_sort_by_liquidity(client):
    _seed(
        {
            "deep": {"volume_24hr": 1.0, "liquidity": 1_000_000.0},
            "thin": {"volume_24hr": 99.0, "liquidity": 1.0},
        }
    )
    # Opposed to the default sort, so a route that dropped the parameter fails.
    assert _slugs(client, "sort=liquidity") == ["deep", "thin"]
    assert _slugs(client, "") == ["thin", "deep"]


def test_sort_by_competitive_differs_from_liquidity(client):
    _seed(
        {
            "deep": {"liquidity": 1_000_000.0, "competitive": 0.1},
            "contested": {"liquidity": 1.0, "competitive": 0.99},
        }
    )
    assert _slugs(client, "sort=liquidity") == ["deep", "contested"]
    assert _slugs(client, "sort=competitive") == ["contested", "deep"]


def test_sort_by_ending_soon_is_ascending(client):
    _seed({"later": {"end_date": 9_000}, "sooner": {"end_date": 1_000}})
    assert _slugs(client, "sort=endingSoon") == ["sooner", "later"]


def test_an_unknown_sort_falls_back_instead_of_erroring(client):
    """`sort` is caller-supplied; a 500 here would let anyone take the home
    page down with a query string."""
    _seed({"lo": {"volume_24hr": 1.0}, "hi": {"volume_24hr": 99.0}})
    resp = client.get("/events?limit=10&sort=nonsense")
    assert resp.status_code == 200
    assert [e["slug"] for e in resp.json()] == ["hi", "lo"]


def test_the_cache_does_not_serve_one_sort_to_another(client):
    """The sort MUST be part of the cache key, or a liquidity-ordered page is
    served to a volume-ordered request for up to a whole TTL."""
    _seed(
        {
            "deep": {"volume_24hr": 1.0, "liquidity": 1_000_000.0},
            "thin": {"volume_24hr": 99.0, "liquidity": 1.0},
        }
    )
    assert _slugs(client, "sort=liquidity") == ["deep", "thin"]
    assert _slugs(client, "sort=volume24h") == ["thin", "deep"]


def test_sort_composes_with_a_tag_filter(client):
    _seed({"a": {"liquidity": 5.0}, "b": {"liquidity": 9.0}})
    resp = client.get("/events?limit=10&sort=liquidity&tag=nothing-matches-this")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_events_sort.py -q -k sort`
Expected: FAIL — `test_sort_by_liquidity` returns `["thin", "deep"]`, because the unknown `sort` parameter is ignored.

- [ ] **Step 3: Widen the service**

In `agentpit/services/event_service.py`, add the import:

```python
from agentpit.datastructures.event_sort import EventSort
```

Add `sort: EventSort | None = None` as the last parameter of BOTH `list_events` and `list_events_gamma`, and pass `sort=sort` into each one's `TableRead.list_events_with_markets(...)` call.

- [ ] **Step 4: Widen the route and its cache key**

In `agentpit/api/routes/events.py`, add the import:

```python
from agentpit.datastructures.event_sort import EventSort
```

The cache key gains a sixth position. Change the annotation:

```python
_events_cache: dict[
    tuple[int, int, str | None, str | None, tuple[str, ...], str],
    tuple[float, list[GammaEvent]],
] = {}
```

In `_list_events_cached`, add a `sort: str | None = None` parameter, resolve it once, and put the RESOLVED value in the key:

```python
    resolved_sort = EventSort.parse(sort)
    key = (
        limit,
        offset,
        normalized or None,
        normalized_tag,
        normalized_subtags,
        # The resolved member, not the raw string: `?sort=nonsense` and no
        # `sort` at all produce the same page, so they must share one entry
        # rather than filling the cache with junk keys.
        resolved_sort.value,
    )
```

and forward it: `service.list_events_gamma(..., sort=resolved_sort)`.

Add the parameter to the route:

```python
    sort: str | None = None,
```

and pass `sort=sort` into `_list_events_cached`.

Update the module docstring's cache-key sentence to name the sort.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_events_sort.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `tests/api/test_events_cache.py` calls `_list_events_cached` with keyword arguments only and never builds a key tuple itself, so a defaulted sixth parameter leaves it working. If it fails, read the failure — do not edit the test to fit.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/event_service.py agentpit/api/routes/events.py \
        tests/api/test_events_sort.py
git commit -m "feat(events): GET /events?sort= with the sort in the cache key"
```

---

## Task 6: The UI asks the server for its order

**Files:**
- Modify: `ui/src/types/gamma.ts`, `ui/src/types/event.ts`
- Modify: `ui/src/api/events.ts`
- Modify: `ui/src/pages/MarketsPage.tsx`
- Test: `ui/src/api/events.test.ts` (append)

**Interfaces:**
- Consumes: `GET /events?sort=` (Task 5); the wire fields from Task 4.
- Produces: `ListEventsParams.sort?: string | undefined`; `useEventsInfinite(tag, subtags, sort)`.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/api/events.test.ts`:

```ts
describe("listEvents sort param", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset().mockResolvedValue([]));

  function requestedPath(): string {
    return String(vi.mocked(apiFetch).mock.calls[0]?.[0]);
  }

  it("serialises the sort", async () => {
    await listEvents({ limit: 20, offset: 0, sort: "liquidity" });
    expect(requestedPath()).toContain("sort=liquidity");
  });

  it("omits the sort when absent or blank, so the server picks its default", async () => {
    await listEvents({ limit: 20, offset: 0, sort: "  " });
    expect(requestedPath()).not.toContain("sort=");
    await listEvents({ limit: 20, offset: 0 });
    expect(String(vi.mocked(apiFetch).mock.calls[1]?.[0])).not.toContain("sort=");
  });

  it("keeps carrying the tag filters alongside it", async () => {
    await listEvents({
      limit: 20,
      offset: 0,
      sort: "competitive",
      tag: "politics",
      subtags: ["trump"],
    });
    const path = requestedPath();
    expect(path).toContain("sort=competitive");
    expect(path).toContain("tag=politics");
    expect(path).toContain("subtag=trump");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `ui/`: `npx vitest run src/api/events.test.ts`
Expected: FAIL — `sort` is not a property of `ListEventsParams`, and the path carries no `sort=`.

- [ ] **Step 3: Carry the new fields on the types**

In `ui/src/types/gamma.ts`, add to `GammaEvent` beside `volume`:

```ts
  /** Order-book depth, stringified (Gamma convention). "0" when unsynced. */
  liquidity: string;
  /** How contested the odds are, 0..1, stringified. "0" when unsynced. */
  competitive: string;
```

In `ui/src/types/event.ts`, add to `Event` beside `volume`:

```ts
  /** Order-book depth in USD; null when never synced from upstream. */
  liquidity: number | null;
  /** How contested the odds are, 0..1; null when never synced. */
  competitive: number | null;
```

- [ ] **Step 4: Send the sort and map the new fields**

In `ui/src/api/events.ts`, extend `ListEventsParams`:

```ts
  /** Server-side ordering; omitted/blank lets the server pick its default. */
  sort?: string | undefined;
```

In `gammaToEventWithMarkets`, add to the `Event` literal beside `volume`:

```ts
    liquidity: parseVolume(g.liquidity),
    competitive: parseVolume(g.competitive),
```

In `listEvents`, after the subtag loop:

```ts
  if (params.sort && params.sort.trim()) {
    search.set("sort", params.sort.trim());
  }
```

Replace `useEventsInfinite` so the sort is a parameter AND part of the query key:

```ts
export function useEventsInfinite(
  tag: string | null = null,
  subtags: string[] = [],
  sort: string | null = null,
) {
  const normalizedTag = tag?.trim() || null;
  // Sorted so the same OR set in a different click order reuses one page chain
  // instead of refetching from scratch.
  const normalizedSubtags = [...subtags].map((s) => s.trim()).filter(Boolean).sort();
  const normalizedSort = sort?.trim() || null;
  return useInfiniteQuery({
    // The sort is part of the key for the same reason the filters are:
    // changing it must start a fresh page chain. Appending a differently
    // ordered page onto the old one is exactly the bug this replaces.
    queryKey: [
      "events",
      "infinite",
      EVENTS_PAGE_SIZE,
      normalizedTag,
      normalizedSubtags.join(","),
      normalizedSort,
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listEvents({
        limit: EVENTS_PAGE_SIZE,
        offset: pageParam,
        tag: normalizedTag ?? undefined,
        subtags: normalizedSubtags,
        sort: normalizedSort ?? undefined,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.nextOffset : undefined,
    // Poll so newly-synced markets appear on the home page without a manual
    // refresh (a sync streams markets in over a few seconds). Only refetches
    // while the tab is visible (refetchIntervalInBackground defaults to false).
    refetchInterval: 5000,
  });
}
```

- [ ] **Step 5: Delete the client-side sort**

In `ui/src/pages/MarketsPage.tsx`:

Pass the sort into the hook — the call is currently
`useEventsInfinite(selectedCategory, selectedFacetSlugs)`:

```tsx
  } = useEventsInfinite(selectedCategory, selectedFacetSlugs, sortMode);
```

Then replace the whole `filtered` memo. It currently filters by the search box and then runs a large `sorted.sort(...)` block; the sorting is now the server's job, and only the search filter remains:

```tsx
  const filtered = useMemo(() => {
    // No client-side sort: the server orders the whole catalogue, and
    // re-sorting the pages that happen to be loaded is what put a $686M event
    // on page two. Search still runs here, so it still needs eager paging.
    if (trimmedQuery.length === 0) return events;
    return events.filter(({ event, markets }) => {
      if (event.title.toLowerCase().includes(trimmedQuery)) return true;
      return markets.some((m) =>
        (m.outcome_label ?? m.question).toLowerCase().includes(trimmedQuery),
      );
    });
  }, [events, trimmedQuery]);
```

`SortMode`, `SORT_OPTIONS` and `DEFAULT_SORT_OPTION` all stay — their values are already the wire strings the server expects. Leave the sort menu markup untouched.

- [ ] **Step 6: Verify the UI**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass. Typecheck is the real gate for `MarketsPage`: vitest runs in the node environment with no `@testing-library/react`, so the page cannot be render-tested.

- [ ] **Step 7: Commit**

```bash
git add ui/src/types/gamma.ts ui/src/types/event.ts ui/src/api/events.ts \
        ui/src/api/events.test.ts ui/src/pages/MarketsPage.tsx
git commit -m "feat(events): the markets page asks the server for its order"
```

---

## Task 7: Backfill the metrics for events outside the sync window

**Files:**
- Create: `scripts/backfill_event_metrics.py`

**Interfaces:**
- Consumes: `TableWrite.update_event_metrics` (Task 2).
- Produces: `.venv/bin/python -m scripts.backfill_event_metrics [--dry-run]`.

**Why this task exists:** the sync only re-binds markets inside its current
Gamma window — the top `SYNC_MAX_MARKETS` clearing `SYNC_LIQUIDITY_MIN`
(1000 and 5000 on production). Events that have since dropped out of that
window would keep NULL metrics forever and sort last under Liquidity and
Competitive. The same gap bit the tag rollout, where 522 of 929 live events
were affected. Widening the sync's own floor is NOT the fix:
`create_polygon_market_if_does_not_exist` mints any market it has not seen, so
a zero-floor pass grows the catalogue on chain as a side effect.

- [ ] **Step 1: Write the script**

Create `scripts/backfill_event_metrics.py`. It mirrors the existing
`scripts/backfill_market_tags.py` — **read that file first and follow its
shape**: same `--dry-run` flag, same 50-ids-per-call batching against
`GET https://gamma-api.polymarket.com/events?limit=100&id=…`, same
`User-Agent: agentpit-backfill` header (Gamma 403s a bare urllib UA), same
per-batch try/except so one failure does not lose the rest, same
`db.close()` at the end.

The differences:

```python
    with db.read() as conn:
        rows = conn.execute(
            """
            SELECT EVENT_ID, POLYMARKET_EVENT_ID AS PM_ID
            FROM events
            WHERE POLYMARKET_EVENT_ID IS NOT NULL
              AND (LIQUIDITY IS NULL OR COMPETITIVE IS NULL)
            """
        ).fetchall()
```

and, per fetched event:

```python
            TableWrite.update_event_metrics(
                conn,
                event_id,
                _as_float(payload.get("liquidity")),
                _as_float(payload.get("competitive")),
            )
```

with a module-local coercion, because upstream stringifies some numbers and
omits others:

```python
def _as_float(value: object) -> float | None:
    """A number, or None for anything unparseable.

    None is the signal `update_event_metrics` skips on, so an event upstream
    has no figure for keeps whatever it already had rather than being blanked.
    """
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
```

Give the module a docstring explaining the sync-window gap in the terms above,
and state that it only ever fills — it selects rows where a metric IS NULL, so
re-running it is a no-op over what it already wrote.

- [ ] **Step 2: Dry-run it**

Run: `.venv/bin/python -m scripts.backfill_event_metrics --dry-run`
Expected: a count of events it would fill, and no database writes.

- [ ] **Step 3: Run it for real against the local database**

Run: `.venv/bin/python -m scripts.backfill_event_metrics`
Expected: a completion line naming how many events were filled.

- [ ] **Step 4: Confirm it is idempotent**

Run: `.venv/bin/python -m scripts.backfill_event_metrics --dry-run`
Expected: `0` events to fill — a second pass has nothing to do.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. The script is not imported by the app.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_event_metrics.py
git commit -m "feat(events): backfill liquidity and competitive from upstream"
```

---

## Task 8: Full verification

**Files:** none — this task only runs and reports.

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Do NOT source `.env` first.

- [ ] **Step 2: UI suite**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 3: Confirm the client-side sort is gone**

```bash
grep -n "sorted.sort\|aLiveCount\|bLiveCount" ui/src/pages/MarketsPage.tsx
```
Expected: no output. Any hit means the old comparator survived.

- [ ] **Step 4: Confirm the sort menu still offers all six**

```bash
grep -c "key: \"" ui/src/pages/MarketsPage.tsx
```
Expected: at least 6 — `SORT_OPTIONS` is unchanged.

- [ ] **Step 5: Prove the ordering end to end against a real database**

```bash
.venv/bin/python - <<'PY'
from agentpit.config import Settings
from agentpit.datastructures.event_sort import EventSort
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

db = DbSession(Settings().database_url)
with db.read() as conn:
    for sort in EventSort:
        pairs, total = TableRead.list_events_with_markets(
            conn, limit=5, offset=0, sort=sort
        )
        head = [(ev.slug[:28], ev.volume_24hr, ev.liquidity, ev.competitive)
                for ev, _ in pairs]
        print(f"{sort.value:>13}  total={total}")
        for h in head:
            print("   ", h)
db.close()
PY
```
Expected: each sort returns a DIFFERENT leading event where the data differs,
and no ordering puts a `None` metric above a populated one.

- [ ] **Step 6: Report**

State the backend test count, the UI test count, and the results of Steps 3–5.
If anything failed, report the actual output rather than a summary.

---

## Self-Review

**Design coverage.** All five agreed points map to tasks: the two columns → Task 2; the sync capture → Task 2; `?sort=` with the ORDER BY switch and the cache key → Tasks 1, 3, 5; the UI passing the sort and losing its client sort → Task 6; the backfill → Task 7. The wire plumbing the UI needs to receive the new fields is Task 4, which the five-point summary implied but did not name.

**Placeholders.** None. Every code step carries the code; every test step carries the assertions. Task 7 is the one place that says "follow the shape of an existing file" rather than repeating ~90 lines verbatim — it names the file, lists every property to copy, and gives the three fragments that differ.

**Type consistency.** `EventSort` is defined in Task 1 and consumed as `EventSort | None` in Tasks 3 and 5. `update_event_metrics(db, event_id, liquidity, competitive)` is defined in Task 2 and called with that exact arity in Tasks 3 (test helper), 5 (test helper) and 7. `_extract_event_metadata`'s two new keys, `"liquidity"` and `"competitive"`, are produced in Task 2 and read in Task 2's own call site. `GammaEvent.liquidity/competitive` (Task 4) match the TypeScript `GammaEvent` fields (Task 6). `useEventsInfinite(tag, subtags, sort)` is defined in Task 6 and called with that arity in the same task.

**Known risks flagged in-task.** Task 2 Step 6 tells the implementer to verify `_as_float`'s behaviour on unparseable input rather than assume it. Task 5 Step 6 warns against editing `test_events_cache.py` to fit. Task 3 explains why the one f-string interpolation into SQL is safe, so a reviewer does not have to re-derive it.
