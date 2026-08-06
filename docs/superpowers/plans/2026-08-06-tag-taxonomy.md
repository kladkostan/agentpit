# Tag-Driven Category Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the real Polymarket tags we already fetch and discard, so the markets sidebar offers ~16 categories with up to 20 real subcategories each instead of 8 categories with 3 hardcoded keyword filters.

**Architecture:** A new `market_tags` table mirrors Gamma's per-market tag list, written on every sync pass by the function that currently collapses those tags into one category. An event's tag set is the union over its markets, computed by join. One `GET /tags` endpoint serves the curated top-level list with facets nested; `GET /events` gains `tag` and `subtag` filters so subcategory filtering moves from the client to the server.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres, pydantic; React 18 + TypeScript + Vite, TanStack Query, vitest.

**Spec:** `docs/superpowers/specs/2026-08-06-tag-taxonomy-design.md`

## Global Constraints

- Branch is `mvp`. Do not create a worktree; work in the repo.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env` before pytest** — `tests/conftest.py` uses `os.environ.setdefault`, so a sourced `.env` defeats every default and causes live-sync flakes.
- UI verification, run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. All four must pass.
- `ui/` vitest runs in the **node** environment. `@testing-library/react` is **not installed**. Component rendering in a test is impossible — only pure-logic `.ts` tests.
- `tsconfig` sets `exactOptionalPropertyTypes`: an optional property that can be absent must be typed `foo?: string | undefined`, not `foo?: string`.
- **No visual change to the markets page.** Every component, Tailwind class, icon and expand/collapse behaviour in `ui/src/pages/MarketsPage.tsx` stays exactly as it is. Only the data filling the existing sidebar changes. Do not add event counts to labels.
- All DB rows are dict-style and **case-insensitive** (`ci_dict_row` in `agentpit/db/row_factory.py`): `row["SLUG"]` and `row["slug"]` both work.
- The schema has **no foreign keys anywhere**. Do not add one.
- `TableCreate`, `TableRead`, `TableWrite` are classes of `@staticmethod`s. Intra-class calls go through the class name, never `self`/`cls`.
- Every DDL statement must be idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`) — `create_all_tables` runs on every app construction.
- Do not remove the `CATEGORY` column, `resolve_category`, `category_rank`, `_sync_event_category`, or the `?category=` query param. They stay for the local-market creation path and `EventDetailPage`'s badge.

---

## File Structure

**Create:**

| Path | Responsibility |
| --- | --- |
| `agentpit/polymarket/tag_taxonomy.py` | Curated nav order, blocked slugs, thresholds, slug normalisation. Pure — no DB, no HTTP. |
| `agentpit/datastructures/tag.py` | `TagFacet`, `TagNavEntry`, `ListTagsResponse` pydantic models. |
| `agentpit/api/routes/tags.py` | `GET /tags` + its TTL cache. |
| `ui/src/api/tags.ts` | `listTags()` + `useTags()`. |
| `tests/polymarket/test_tag_taxonomy.py` | Task 1 |
| `tests/db/test_market_tags_dal.py` | Tasks 2, 4, 5 |
| `tests/polymarket/test_tag_sync.py` | Task 3 |
| `tests/api/test_tags.py` | Task 6 |
| `ui/src/api/tags.test.ts` | Task 8 |

**Modify:**

| Path | Change |
| --- | --- |
| `agentpit/db/table_create.py` | `create_market_tags_table` + register in `create_all_tables` |
| `agentpit/db/table_write.py` | `replace_market_tags` |
| `agentpit/db/table_read.py` | `list_tag_nav`, `list_tag_facets`, `list_events_with_markets(tag, subtags)` |
| `agentpit/polymarket/polymarket_sync.py` | write tags inside `bind_market_to_upstream_event` |
| `agentpit/services/event_service.py` | `list_tags()`, `list_events_gamma(tag, subtags)` |
| `agentpit/api/routes/events.py` | `tag` + `subtag` params, extended cache key |
| `agentpit/api/app.py` | `app.include_router(tags.router)` |
| `tests/conftest.py` | clear the new `/tags` cache |
| `ui/src/api/events.ts` | `tag` + `subtags` params |
| `ui/src/pages/MarketsPage.tsx` | consume `/tags`; delete the hardcoded map |

---

## Task 1: Tag taxonomy constants

**Files:**
- Create: `agentpit/polymarket/tag_taxonomy.py`
- Test: `tests/polymarket/test_tag_taxonomy.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `NAV_SLUGS: tuple[str, ...]`, `BLOCKED_SLUGS: frozenset[str]`, `DEPRECATED_PREFIX: str`, `MIN_NAV_EVENTS: int`, `MAX_FACET_COVERAGE: float`, `MAX_FACETS: int`, `normalize_slug(value: object) -> str | None`, `is_blocked(slug: str) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_tag_taxonomy.py`:

```python
"""Pure taxonomy rules: slug normalisation and the blocked-tag policy."""

from __future__ import annotations

from agentpit.polymarket.tag_taxonomy import (
    BLOCKED_SLUGS,
    MAX_FACET_COVERAGE,
    MAX_FACETS,
    MIN_NAV_EVENTS,
    NAV_SLUGS,
    is_blocked,
    normalize_slug,
)


def test_normalize_slug_lowercases_and_strips():
    # Gamma is inconsistent: the live crypto facet list contained a literal
    # "1H" beside lowercase siblings. Unnormalised, that splits one facet in two.
    assert normalize_slug("  1H ") == "1h"
    assert normalize_slug("Pop-Culture") == "pop-culture"


def test_normalize_slug_rejects_non_strings_and_blanks():
    assert normalize_slug(None) is None
    assert normalize_slug(123) is None
    assert normalize_slug("") is None
    assert normalize_slug("   ") is None


def test_is_blocked_covers_operational_tags():
    assert is_blocked("hide-from-new")
    assert is_blocked("recurring")
    assert is_blocked("up-or-down")


def test_is_blocked_matches_the_deprecated_prefix():
    assert is_blocked("deprec-us-election")
    assert not is_blocked("deprecation-policy")


def test_is_blocked_leaves_real_topics_alone():
    for slug in ("politics", "sports", "tennis", "games", "iran", "bitcoin"):
        assert not is_blocked(slug), slug


def test_games_is_not_blocklisted():
    # `games` is uninformative under `sports` (832 of 895 events), but the
    # coverage rule removes it there on the data. Under a parent where it is
    # genuinely selective it must survive.
    assert "games" not in BLOCKED_SLUGS


def test_nav_slugs_are_unique_normalised_and_ordered_politics_first():
    assert NAV_SLUGS[0] == "politics"
    assert len(set(NAV_SLUGS)) == len(NAV_SLUGS)
    for slug in NAV_SLUGS:
        assert normalize_slug(slug) == slug


def test_no_nav_slug_is_blocked():
    for slug in NAV_SLUGS:
        assert not is_blocked(slug), slug


def test_thresholds_have_the_agreed_values():
    assert MIN_NAV_EVENTS == 10
    assert MAX_FACET_COVERAGE == 0.9
    assert MAX_FACETS == 20
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_tag_taxonomy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.polymarket.tag_taxonomy'`

- [ ] **Step 3: Write the implementation**

Create `agentpit/polymarket/tag_taxonomy.py`:

```python
"""Which Polymarket tags the UI navigates by, and which it ignores.

Gamma returns a flat unordered ``tags[]`` per market — roughly 4.6 of them,
drawn from a catalogue of 759 across our own event set. Most are real topics
("Trump", "Bitcoin", "Strait of Hormuz"); a minority describe how a market is
scheduled or settled rather than what it is about. This module holds the
editorial judgement about which is which, so the DAL and the API stay
mechanical.
"""

from __future__ import annotations

# The top-level navigation, in display order. This is an ALLOW list, not a
# ranking hint: a slug absent here never becomes a category. It is also only
# half the rule — a slug listed here still renders only when the database
# actually holds MIN_NAV_EVENTS events carrying it, so a tab can never lead to
# an empty grid.
#
# Ordering is editorial and mirrors Polymarket's own row, which is likewise not
# sorted by size (they lead with Politics though Sports is three times larger).
NAV_SLUGS: tuple[str, ...] = (
    "politics",
    "sports",
    "crypto",
    "elections",
    "geopolitics",
    "tennis",
    "esports",
    "soccer",
    "weather",
    "tech",
    "pop-culture",
    "finance",
    "economy",
    "world",
    "ai",
    "business",
    "science",
)

# Operational tags: they describe a market's cadence, its settlement mechanic
# or its visibility in Polymarket's own UI, and tell a reader nothing about the
# subject. `hide-from-new` alone sits on 236 of our events.
#
# `games` is deliberately NOT here. It is uninformative under `sports` (832 of
# 895 events) but MAX_FACET_COVERAGE removes it there on the data rather than on
# a hunch, and under a parent where it is genuinely selective it should survive.
BLOCKED_SLUGS: frozenset[str] = frozenset(
    {
        # cadence
        "recurring",
        "daily",
        "weekly",
        "monthly",
        "yearly",
        "hourly",
        "1h",
        "4h",
        "today",
        "extended",
        # settlement mechanics
        "up-or-down",
        "hit-price",
        "multi-strikes",
        "price-milestone",
        "neg-risk",
        # upstream UI plumbing
        "hide-from-new",
        "new",
        "trending",
        "all",
        "main-election",
        "earn-4",
    }
)

# Polymarket retires a tag by renaming it rather than deleting it, leaving
# rows like `deprec-us-election` in the live feed.
DEPRECATED_PREFIX = "deprec-"

# A top-level entry below this many events is hidden rather than rendered as a
# near-empty tab. On the 2026-08-06 snapshot this hides `science` (9 events).
MIN_NAV_EVENTS = 10

# A facet matching more than this share of its parent says nothing — it is the
# parent under another name. Removes `games` from `sports` (832 of 895).
MAX_FACET_COVERAGE = 0.9

# Longest subcategory list we will render under one category.
MAX_FACETS = 20


def normalize_slug(value: object) -> str | None:
    """Lowercase and strip a tag slug, or return None if it is not usable.

    Non-strings are rejected rather than coerced: Gamma has been observed
    returning nulls inside ``tags[]``, and ``str(None)`` would silently invent
    a tag called "none".
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def is_blocked(slug: str) -> bool:
    """True when a slug must never be shown as a category or a facet."""
    return slug in BLOCKED_SLUGS or slug.startswith(DEPRECATED_PREFIX)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/polymarket/test_tag_taxonomy.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS (no regressions — this task adds a leaf module).

- [ ] **Step 6: Commit**

```bash
git add agentpit/polymarket/tag_taxonomy.py tests/polymarket/test_tag_taxonomy.py
git commit -m "feat(tags): taxonomy constants and slug normalisation"
```

---

## Task 2: `market_tags` table and its write path

**Files:**
- Modify: `agentpit/db/table_create.py` (add a method; register it in `create_all_tables` at the end of the file)
- Modify: `agentpit/db/table_write.py` (add a method to `TableWrite`)
- Test: `tests/db/test_market_tags_dal.py`

**Interfaces:**
- Consumes: `normalize_slug` from Task 1.
- Produces:
  - `TableCreate.create_market_tags_table(conn: psycopg.Connection) -> None`
  - `TableWrite.replace_market_tags(db: psycopg.Connection, *, market_id: int, tags: list[tuple[str, str]]) -> None` — `tags` is a list of `(slug, label)` pairs, already normalised by the caller.

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_market_tags_dal.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q`
Expected: FAIL — `AttributeError: type object 'TableCreate' has no attribute 'create_market_tags_table'`

- [ ] **Step 3: Add the table**

In `agentpit/db/table_create.py`, add this method to `TableCreate` immediately after `create_markets_table`:

```python
    @staticmethod
    def create_market_tags_table(conn: psycopg.Connection) -> None:
        """Polymarket's per-market tag list, mirrored verbatim.

        Tags live on the MARKET, not the event, because that is where Gamma
        puts them and because replacing one market's set on each sync pass is
        self-healing: a tag removed upstream disappears here too. An
        event-level union could only ever grow. An event's tag set is the
        union over its markets, taken by join at read time.

        No foreign key on MARKET_ID — the schema uses plain columns plus
        indexes throughout (markets.EVENT_ID has none either).
        """
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_tags (
                MARKET_ID BIGINT NOT NULL,
                SLUG TEXT NOT NULL,
                LABEL TEXT NOT NULL,
                PRIMARY KEY (MARKET_ID, SLUG)
            )
            """
        )
        # The facet and nav queries both start from a slug, so this index is
        # the one that matters; MARKET_ID is already covered by the PK's
        # leading column.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_tags_slug ON market_tags(SLUG)"
        )
```

Then register it in `create_all_tables` — add the line after `create_markets_table`:

```python
        TableCreate.create_markets_table(conn)
        TableCreate.create_market_tags_table(conn)
```

- [ ] **Step 4: Add the write method**

In `agentpit/db/table_write.py`, add to `TableWrite` immediately after `attach_market_to_event`:

```python
    @staticmethod
    def replace_market_tags(
        db: psycopg.Connection, *, market_id: int, tags: list[tuple[str, str]]
    ) -> None:
        """Set this market's tag rows to exactly ``tags``, a list of
        ``(slug, label)`` pairs the caller has already normalised.

        Replace rather than merge: a tag Polymarket removed must disappear
        locally on the next sync pass, and only a full rewrite of one market's
        set achieves that without needing to know the previous contents.

        Duplicate slugs within one call are collapsed. Two upstream entries can
        normalise to the same slug (Gamma has returned both "1H" and "1h"), and
        a duplicate row would violate the primary key and abort the statement,
        taking the caller's whole transaction with it.
        """
        db.execute("DELETE FROM market_tags WHERE MARKET_ID = %s", (market_id,))
        deduped: dict[str, str] = {}
        for slug, label in tags:
            deduped.setdefault(slug, label)
        if not deduped:
            return
        db.executemany(
            "INSERT INTO market_tags (MARKET_ID, SLUG, LABEL) VALUES (%s, %s, %s)",
            [(market_id, slug, label) for slug, label in deduped.items()],
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_write.py tests/db/test_market_tags_dal.py
git commit -m "feat(tags): market_tags table and replace-on-write"
```

---

## Task 3: The sync writes tags

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` (add a helper; call it from `bind_market_to_upstream_event`)
- Test: `tests/polymarket/test_tag_sync.py`

**Interfaces:**
- Consumes: `TableWrite.replace_market_tags(db, *, market_id, tags)` from Task 2; `normalize_slug` from Task 1.
- Produces: `extract_tags(pm_market: dict) -> list[tuple[str, str]] | None` — `None` means "upstream told us nothing, leave stored tags alone"; a list (possibly empty) means "this is the authoritative set".

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_tag_sync.py`:

```python
"""The sync's tag extraction and its do-not-clobber guard."""

from __future__ import annotations

from agentpit.polymarket.polymarket_sync import extract_tags


def test_extract_tags_returns_slug_label_pairs():
    pm = {"tags": [{"slug": "politics", "label": "Politics"}]}
    assert extract_tags(pm) == [("politics", "Politics")]


def test_extract_tags_normalises_the_slug_but_not_the_label():
    pm = {"tags": [{"slug": " Pop-Culture ", "label": "Culture"}]}
    assert extract_tags(pm) == [("pop-culture", "Culture")]


def test_extract_tags_falls_back_to_the_slug_when_the_label_is_missing():
    assert extract_tags({"tags": [{"slug": "iran"}]}) == [("iran", "iran")]
    assert extract_tags({"tags": [{"slug": "iran", "label": ""}]}) == [("iran", "iran")]
    assert extract_tags({"tags": [{"slug": "iran", "label": 7}]}) == [("iran", "iran")]


def test_extract_tags_returns_none_when_tags_is_absent_or_null():
    """The guard that matters. A Gamma request without include_tag=true comes
    back with tags: null; treating that as "no tags" would wipe good rows on
    every pass through such a code path."""
    assert extract_tags({}) is None
    assert extract_tags({"tags": None}) is None


def test_extract_tags_returns_none_when_tags_is_not_a_list():
    assert extract_tags({"tags": "politics"}) is None
    assert extract_tags({"tags": {"slug": "politics"}}) is None


def test_extract_tags_returns_empty_list_for_an_empty_upstream_list():
    """Distinct from None: upstream positively says this market has no tags."""
    assert extract_tags({"tags": []}) == []


def test_extract_tags_skips_malformed_entries_without_raising():
    """One bad entry must not stall the pass — a raise here would skip this
    market on every future sync, permanently."""
    pm = {
        "tags": [
            "not-a-dict",
            None,
            {"label": "No slug"},
            {"slug": None, "label": "Null slug"},
            {"slug": 42, "label": "Numeric slug"},
            {"slug": "   ", "label": "Blank slug"},
            {"slug": "iran", "label": "Iran"},
        ]
    }
    assert extract_tags(pm) == [("iran", "Iran")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_tag_sync.py -q`
Expected: FAIL — `ImportError: cannot import name 'extract_tags'`

- [ ] **Step 3: Add the extractor**

In `agentpit/polymarket/polymarket_sync.py`, add the import beside the existing `category_resolver` import:

```python
from agentpit.polymarket.tag_taxonomy import normalize_slug
```

Add this function immediately above `bind_market_to_upstream_event`:

```python
def extract_tags(pm_market: dict) -> list[tuple[str, str]] | None:
    """Pull ``(slug, label)`` pairs off an upstream market.

    Returns ``None`` — meaning "upstream said nothing, keep what is stored" —
    when ``tags`` is absent, null, or not a list. That distinction is the whole
    point: a Gamma request without ``include_tag=true`` returns ``tags: null``
    for every market, and treating that as an empty set would wipe good rows on
    every pass through such a code path. An empty LIST is different: upstream
    positively says this market has no tags, and the stored set should clear.

    Malformed entries are skipped individually rather than raised on. Raising
    here would abort this market's binding on every future pass, permanently.

    The label is only ever a display string, so a missing or non-string one
    falls back to the slug rather than dropping an otherwise good tag.
    """
    raw = pm_market.get("tags")
    if not isinstance(raw, list):
        return None
    out: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slug = normalize_slug(entry.get("slug"))
        if slug is None:
            continue
        label = entry.get("label")
        out.append((slug, label if isinstance(label, str) and label.strip() else slug))
    return out
```

- [ ] **Step 4: Call it from the bind path**

In `bind_market_to_upstream_event`, immediately after the existing
`TableWrite.attach_market_to_event(...)` call at the end of the function, append:

```python
    # Mirror the upstream tag list. This is the same payload `resolve_category`
    # above collapses into one CATEGORY; storing it whole is what lets the
    # sidebar offer real subcategories. Skipped entirely when upstream carried
    # no tags list, so a caller without include_tag=true cannot clear good rows.
    tags = extract_tags(pm_market)
    if tags is not None:
        TableWrite.replace_market_tags(db, market_id=market.market_id, tags=tags)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/polymarket/test_tag_sync.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_tag_sync.py
git commit -m "feat(tags): sync mirrors upstream tags into market_tags"
```

---

## Task 4: Nav and facet queries

**Files:**
- Modify: `agentpit/db/table_read.py` (add two methods to `TableRead`, beside `list_event_categories`)
- Test: `tests/db/test_market_tags_dal.py` (append)

**Interfaces:**
- Consumes: `market_tags` (Task 2); `TableWrite.replace_market_tags` (Task 2).
- Produces:
  - `TableRead.list_tag_nav(db, *, slugs: list[str], min_events: int) -> list[tuple[str, str, int]]` — unordered `(slug, label, event_count)` for slugs clearing the threshold.
  - `TableRead.list_tag_facets(db, *, parent_slug: str, blocked: frozenset[str], deprecated_prefix: str, limit: int, max_coverage: float) -> list[tuple[str, str, int]]` — finished, count-descending list.

- [ ] **Step 1: Write the failing test**

Append to `tests/db/test_market_tags_dal.py`:

```python
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
```

Add `from agentpit.db.table_read import TableRead` to the file's imports.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q`
Expected: FAIL — `AttributeError: type object 'TableRead' has no attribute 'list_tag_nav'`

- [ ] **Step 3: Write the implementation**

In `agentpit/db/table_read.py`, add both methods to `TableRead` immediately after `list_event_categories`:

```python
    @staticmethod
    def list_tag_nav(
        db: psycopg.Connection, *, slugs: list[str], min_events: int
    ) -> "list[tuple[str, str, int]]":
        """``(slug, label, event_count)`` for each requested slug that carries
        at least ``min_events`` events. Unordered — the caller restores the
        curated order.

        Counts DISTINCT events, not tag rows: one event whose two markets both
        carry `politics` is one Politics event, not two. Markets with no event
        are excluded — an unbound market is not reachable from any listing.

        ``MIN(LABEL)`` rather than an arbitrary pick: after an upstream rename
        the same slug can briefly carry two labels across markets, and the
        answer must not flicker between calls.
        """
        if not slugs:
            return []
        cur = db.execute(
            """
            SELECT mt.SLUG AS SLUG, MIN(mt.LABEL) AS LABEL,
                   COUNT(DISTINCT m.EVENT_ID) AS CNT
            FROM market_tags mt
            JOIN markets m ON m.MARKET_ID = mt.MARKET_ID
            WHERE m.EVENT_ID IS NOT NULL AND mt.SLUG = ANY(%s)
            GROUP BY mt.SLUG
            HAVING COUNT(DISTINCT m.EVENT_ID) >= %s
            """,
            (list(slugs), min_events),
        )
        return [(str(r["SLUG"]), str(r["LABEL"]), int(r["CNT"])) for r in cur.fetchall()]

    @staticmethod
    def list_tag_facets(
        db: psycopg.Connection,
        *,
        parent_slug: str,
        blocked: "frozenset[str]",
        deprecated_prefix: str,
        limit: int,
        max_coverage: float,
    ) -> "list[tuple[str, str, int]]":
        """Tags co-occurring with ``parent_slug``, most common first.

        "Co-occurring" is at EVENT level: a facet counts an event whose tag
        union contains both slugs, even when they arrived on different markets
        of that event.

        Two filters run in Python rather than SQL because both need the
        parent's own total, which the same pass computes: the coverage ceiling
        (a facet matching nearly every event of its parent is the parent under
        another name) and the length cap.
        """
        parent_total = db.execute(
            """
            SELECT COUNT(DISTINCT m.EVENT_ID) AS CNT
            FROM market_tags mt
            JOIN markets m ON m.MARKET_ID = mt.MARKET_ID
            WHERE mt.SLUG = %s AND m.EVENT_ID IS NOT NULL
            """,
            (parent_slug,),
        ).fetchone()["CNT"]
        if not parent_total:
            return []
        cur = db.execute(
            """
            WITH parent_events AS (
                SELECT DISTINCT m.EVENT_ID AS EVENT_ID
                FROM market_tags mt
                JOIN markets m ON m.MARKET_ID = mt.MARKET_ID
                WHERE mt.SLUG = %s AND m.EVENT_ID IS NOT NULL
            )
            SELECT mt.SLUG AS SLUG, MIN(mt.LABEL) AS LABEL,
                   COUNT(DISTINCT m.EVENT_ID) AS CNT
            FROM market_tags mt
            JOIN markets m ON m.MARKET_ID = mt.MARKET_ID
            JOIN parent_events pe ON pe.EVENT_ID = m.EVENT_ID
            WHERE mt.SLUG <> %s
              AND NOT (mt.SLUG = ANY(%s))
              AND mt.SLUG NOT LIKE %s
            GROUP BY mt.SLUG
            ORDER BY CNT DESC, mt.SLUG ASC
            """,
            (parent_slug, parent_slug, list(blocked), f"{deprecated_prefix}%"),
        )
        out: list[tuple[str, str, int]] = []
        for row in cur.fetchall():
            count = int(row["CNT"])
            if count / parent_total > max_coverage:
                continue
            out.append((str(row["SLUG"]), str(row["LABEL"]), count))
            if len(out) >= limit:
                break
        return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q`
Expected: PASS, 18 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_market_tags_dal.py
git commit -m "feat(tags): nav and facet queries"
```

---

## Task 5: Filter the events listing by tag

**Files:**
- Modify: `agentpit/db/table_read.py:604-658` (`list_events_with_markets`)
- Test: `tests/db/test_market_tags_dal.py` (append)

**Interfaces:**
- Consumes: `market_tags` (Task 2).
- Produces: `TableRead.list_events_with_markets(db, limit=100, offset=0, category=None, tag=None, subtags=None)` — `tag: str | None`, `subtags: list[str] | None`. Return type is unchanged: `tuple[list[tuple[Event, list[Market]]], int]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/db/test_market_tags_dal.py`:

```python
# ----- list_events_with_markets tag filtering ---------------------------------


def _titles(result) -> set[str]:
    rows, _total = result
    return {ev.title for ev, _markets in rows}


def _seed_tagged_events(db) -> None:
    _event_with_tagged_markets(db, slug="a", tags_per_market=[["politics", "trump"]])
    _event_with_tagged_markets(db, slug="b", tags_per_market=[["politics", "midterms"]])
    _event_with_tagged_markets(db, slug="c", tags_per_market=[["sports", "tennis"]])
    _event_with_tagged_markets(db, slug="d", tags_per_market=[["crypto", "trump"]])


def test_list_events_filters_by_tag(db):
    _seed_tagged_events(db)
    assert _titles(
        TableRead.list_events_with_markets(db, limit=10, offset=0, tag="politics")
    ) == {"A", "B"}


def test_list_events_tag_filter_reports_a_matching_total(db):
    _seed_tagged_events(db)
    _rows, total = TableRead.list_events_with_markets(
        db, limit=10, offset=0, tag="politics"
    )
    assert total == 2


def test_list_events_subtags_are_ored_within_the_parent(db):
    _seed_tagged_events(db)
    assert _titles(
        TableRead.list_events_with_markets(
            db, limit=10, offset=0, tag="politics", subtags=["trump", "midterms"]
        )
    ) == {"A", "B"}


def test_list_events_subtag_and_tag_compose_with_and(db):
    """Event D carries `trump` but not `politics`. Selecting Politics > Trump
    must not surface it — that is why the parent stays in the query."""
    _seed_tagged_events(db)
    assert _titles(
        TableRead.list_events_with_markets(
            db, limit=10, offset=0, tag="politics", subtags=["trump"]
        )
    ) == {"A"}


def test_list_events_blank_tag_and_empty_subtags_mean_no_filter(db):
    _seed_tagged_events(db)
    for tag in (None, "", "   "):
        assert len(_titles(
            TableRead.list_events_with_markets(db, limit=10, offset=0, tag=tag)
        )) == 4
    assert len(_titles(
        TableRead.list_events_with_markets(db, limit=10, offset=0, subtags=[])
    )) == 4


def test_list_events_tag_filter_matches_across_an_events_markets(db):
    """Market A has `politics`, market B has `trump`; the event has both."""
    _event_with_tagged_markets(db, slug="split", tags_per_market=[["politics"], ["trump"]])
    assert _titles(
        TableRead.list_events_with_markets(
            db, limit=10, offset=0, tag="politics", subtags=["trump"]
        )
    ) == {"Split"}


def test_list_events_tag_composes_with_category(db):
    _event_with_tagged_markets(db, slug="tagged", tags_per_market=[["politics"]])
    TableWrite.upsert_event(db, slug="tagged", title="Tagged", category="Sports")
    assert _titles(
        TableRead.list_events_with_markets(
            db, limit=10, offset=0, category="Sports", tag="politics"
        )
    ) == {"Tagged"}
    assert _titles(
        TableRead.list_events_with_markets(
            db, limit=10, offset=0, category="Crypto", tag="politics"
        )
    ) == set()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q -k list_events`
Expected: FAIL — `TypeError: list_events_with_markets() got an unexpected keyword argument 'tag'`

- [ ] **Step 3: Write the implementation**

Replace the signature and the `where`-building block of `list_events_with_markets` in `agentpit/db/table_read.py`. The method currently starts:

```python
    @staticmethod
    def list_events_with_markets(
        db: psycopg.Connection,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
    ) -> "tuple[list[tuple[Event, list[Market]]], int]":
```

and builds its filter with:

```python
        where = ""
        params: list[object] = []
        normalized_category = category.strip() if category else None
        if normalized_category:
            where = " WHERE LOWER(CATEGORY) = LOWER(%s)"
            params.append(normalized_category)
```

Change the signature to:

```python
    @staticmethod
    def list_events_with_markets(
        db: psycopg.Connection,
        limit: int = 100,
        offset: int = 0,
        category: str | None = None,
        tag: str | None = None,
        subtags: "list[str] | None" = None,
    ) -> "tuple[list[tuple[Event, list[Market]]], int]":
```

and replace the filter block with:

```python
        # Predicates accumulate and are joined with AND; the tag filters are
        # EXISTS subqueries because an event's tag set lives on its markets.
        # `subtags` ORs within itself via ANY() while still ANDing against
        # `tag` — a facet like `trump` also occurs outside `politics`, and
        # dropping the parent would let a Politics > Trump selection surface a
        # non-Politics event.
        clauses: list[str] = []
        params: list[object] = []
        normalized_category = category.strip() if category else None
        if normalized_category:
            clauses.append("LOWER(CATEGORY) = LOWER(%s)")
            params.append(normalized_category)
        normalized_tag = tag.strip().lower() if tag else None
        if normalized_tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM markets m "
                "JOIN market_tags mt ON mt.MARKET_ID = m.MARKET_ID "
                "WHERE m.EVENT_ID = events.EVENT_ID AND mt.SLUG = %s)"
            )
            params.append(normalized_tag)
        normalized_subtags = [
            s.strip().lower() for s in (subtags or []) if s and s.strip()
        ]
        if normalized_subtags:
            clauses.append(
                "EXISTS (SELECT 1 FROM markets m "
                "JOIN market_tags mt ON mt.MARKET_ID = m.MARKET_ID "
                "WHERE m.EVENT_ID = events.EVENT_ID AND mt.SLUG = ANY(%s))"
            )
            params.append(normalized_subtags)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
```

Everything below that — the `COUNT(*)`, the `SELECT ... ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC`, and the member-market fetch — stays exactly as it is. Extend the method's docstring with one paragraph:

```
        ``tag`` and ``subtags`` filter on the tag graph rather than the
        CATEGORY column: an event matches when any of its markets carries the
        slug. They compose with each other and with ``category`` as AND, while
        ``subtags`` ORs within itself. Blank and whitespace-only values count
        as absent, exactly as ``category`` does.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/db/test_market_tags_dal.py -q`
Expected: PASS, 25 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS — in particular `tests/db/test_events_dal.py` and `tests/api/test_events.py`, which exercise the untouched `category` path.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_market_tags_dal.py
git commit -m "feat(tags): filter the events listing by tag and subtags"
```

---

## Task 6: `GET /tags`

**Files:**
- Create: `agentpit/datastructures/tag.py`, `agentpit/api/routes/tags.py`
- Modify: `agentpit/services/event_service.py`, `agentpit/api/app.py:636-649`, `tests/conftest.py`
- Test: `tests/api/test_tags.py`

**Interfaces:**
- Consumes: `TableRead.list_tag_nav`, `TableRead.list_tag_facets` (Task 4); `NAV_SLUGS`, `BLOCKED_SLUGS`, `DEPRECATED_PREFIX`, `MIN_NAV_EVENTS`, `MAX_FACET_COVERAGE`, `MAX_FACETS` (Task 1).
- Produces: `EventService.list_tags() -> ListTagsResponse`; models `TagFacet`, `TagNavEntry`, `ListTagsResponse`; module globals `agentpit.api.routes.tags._tags_cache`, `_TAGS_TTL_S`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_tags.py`:

```python
"""GET /tags — curated order, present-only entries, nested facets, TTL cache."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _seed(events: dict[str, list[str]]) -> None:
    """`{event_slug: [tag_slug, …]}` — one market per event carrying the tags."""
    conn = fresh_test_conn()
    try:
        for slug, tags in events.items():
            event = TableWrite.upsert_event(conn, slug=slug, title=slug.title())
            market = TableWrite.create_market(
                conn,
                CreateMarketRequest(
                    question=f"{slug}?",
                    description="d",
                    erc1155_tokens=[(f"{slug}-y", "Yes"), (f"{slug}-n", "No")],
                    slug=slug,
                    # Derived from the slug, NOT an enumerate index: several
                    # tests call _seed twice, and a restarting counter would
                    # collide on the CONDITION_ID unique index.
                    condition_id=ConditionId(_hex32(slug)),
                    state=MarketState.ACTIVE,
                    event_id=event.event_id,
                ),
                is_polygon_market=False,
            )
            TableWrite.replace_market_tags(
                conn,
                market_id=market.market_id,
                tags=[(t, t.replace("-", " ").title()) for t in tags],
            )
    finally:
        conn.close()


def test_tags_is_empty_when_nothing_is_tagged(client):
    r = client.get("/tags")
    assert r.status_code == 200
    assert r.json() == {"tags": []}


def test_tags_hides_a_slug_below_the_threshold(client):
    """MIN_NAV_EVENTS is 10 — one politics event must not raise a tab that
    would lead to a nearly empty grid."""
    _seed({"e0": ["politics"]})
    assert client.get("/tags").json() == {"tags": []}


def test_tags_returns_present_slugs_in_curated_order(client):
    # 10 sports events and 10 politics events; politics leads NAV_SLUGS.
    _seed(
        {f"s{i}": ["sports"] for i in range(10)}
        | {f"p{i}": ["politics"] for i in range(10)}
    )
    tags = client.get("/tags").json()["tags"]
    assert [t["slug"] for t in tags] == ["politics", "sports"]
    assert tags[0]["label"] == "Politics"
    assert tags[0]["count"] == 10


def test_tags_never_returns_a_slug_absent_from_the_database(client):
    _seed({f"p{i}": ["politics"] for i in range(10)})
    slugs = [t["slug"] for t in client.get("/tags").json()["tags"]]
    assert slugs == ["politics"]


def test_tags_nests_facets_ordered_by_count(client):
    _seed(
        {f"p{i}": ["politics", "elections"] for i in range(10)}
        | {"px": ["politics", "iran"]}
    )
    politics = client.get("/tags").json()["tags"][0]
    assert [(f["slug"], f["count"]) for f in politics["facets"]] == [
        ("elections", 10),
        ("iran", 1),
    ]


def test_tags_omits_blocked_slugs_from_facets(client):
    _seed({f"p{i}": ["politics", "recurring", "iran"] for i in range(10)})
    politics = client.get("/tags").json()["tags"][0]
    assert [f["slug"] for f in politics["facets"]] == ["iran"]


def test_tags_response_is_cached_within_the_ttl(client):
    _seed({f"p{i}": ["politics"] for i in range(10)})
    first = client.get("/tags").json()
    _seed({f"s{i}": ["sports"] for i in range(10)})
    # Sports now clears the threshold, but the cached response predates it.
    assert client.get("/tags").json() == first

    from agentpit.api.routes import tags as tags_route

    tags_route._tags_cache = None
    after = client.get("/tags").json()
    assert [t["slug"] for t in after["tags"]] == ["politics", "sports"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_tags.py -q`
Expected: FAIL — 404 on `/tags` (router not registered).

- [ ] **Step 3: Add the response models**

Create `agentpit/datastructures/tag.py`:

```python
from pydantic import BaseModel


class TagFacet(BaseModel):
    """A subcategory: a tag co-occurring with a top-level one."""

    slug: str
    label: str
    count: int


class TagNavEntry(BaseModel):
    """A top-level category and the subcategories beneath it."""

    slug: str
    label: str
    count: int
    facets: list[TagFacet]


class ListTagsResponse(BaseModel):
    tags: list[TagNavEntry]
```

- [ ] **Step 4: Add the service method**

In `agentpit/services/event_service.py`, add the imports:

```python
from agentpit.datastructures.tag import ListTagsResponse, TagFacet, TagNavEntry
from agentpit.polymarket.tag_taxonomy import (
    BLOCKED_SLUGS,
    DEPRECATED_PREFIX,
    MAX_FACET_COVERAGE,
    MAX_FACETS,
    MIN_NAV_EVENTS,
    NAV_SLUGS,
)
```

and this method immediately after `list_categories`:

```python
    def list_tags(self) -> ListTagsResponse:
        """The curated top-level list, each entry carrying its own facets.

        Facets are nested rather than served from a `?parent=` endpoint because
        the sidebar renders a chevron for every category at once and must know
        which ones have subcategories before any is expanded.

        One nav query plus one facet query per surviving slug — about
        seventeen indexed reads, behind a TTL cache, against data that only
        changes when an hourly sync runs. A single self-joining query would do
        it in one round trip and be markedly harder to read.
        """
        with self._db.read() as conn:
            present = {
                slug: (label, count)
                for slug, label, count in TableRead.list_tag_nav(
                    conn, slugs=list(NAV_SLUGS), min_events=MIN_NAV_EVENTS
                )
            }
            entries: list[TagNavEntry] = []
            # Iterating NAV_SLUGS, not `present`, is what restores the curated
            # order the query's GROUP BY does not preserve.
            for slug in NAV_SLUGS:
                found = present.get(slug)
                if found is None:
                    continue
                label, count = found
                facets = TableRead.list_tag_facets(
                    conn,
                    parent_slug=slug,
                    blocked=BLOCKED_SLUGS,
                    deprecated_prefix=DEPRECATED_PREFIX,
                    limit=MAX_FACETS,
                    max_coverage=MAX_FACET_COVERAGE,
                )
                entries.append(
                    TagNavEntry(
                        slug=slug,
                        label=label,
                        count=count,
                        facets=[
                            TagFacet(slug=s, label=lbl, count=c) for s, lbl, c in facets
                        ],
                    )
                )
        return ListTagsResponse(tags=entries)
```

- [ ] **Step 5: Add the route**

Create `agentpit/api/routes/tags.py`:

```python
import time

from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.tag import ListTagsResponse

router = APIRouter(tags=["tags"])

# The taxonomy only moves when a sync runs, an hour apart, while the markets
# page requests this on every mount. The endpoint takes no parameters, so one
# slot is the whole cache — no key, no eviction policy, no unbounded growth.
_TAGS_TTL_S = 30.0
_tags_cache: tuple[float, ListTagsResponse] | None = None


@router.get("/tags", response_model=ListTagsResponse)
def list_tags(service: EventServiceDep) -> ListTagsResponse:
    global _tags_cache
    now = time.monotonic()
    hit = _tags_cache
    if hit is not None and now - hit[0] < _TAGS_TTL_S:
        return hit[1]
    result = service.list_tags()
    _tags_cache = (now, result)
    return result
```

- [ ] **Step 6: Register the router**

In `agentpit/api/app.py`, add `tags` to the parenthesised
`from agentpit.api.routes import (...)` block that starts at line 19, keeping
its alphabetical order, then add the registration after
`app.include_router(events.router)`:

```python
    app.include_router(events.router)
    app.include_router(tags.router)
```

- [ ] **Step 7: Clear the cache between tests**

In `tests/conftest.py`, beside the existing `_events_route._events_cache.clear()`, add:

```python
    # Same reason as the events cache above: /tags holds a single 30s slot, so
    # a response built from a previous test's rows would be served to the next.
    from agentpit.api.routes import tags as _tags_route

    _tags_route._tags_cache = None
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_tags.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 9: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add agentpit/datastructures/tag.py agentpit/api/routes/tags.py \
        agentpit/services/event_service.py agentpit/api/app.py \
        tests/conftest.py tests/api/test_tags.py
git commit -m "feat(tags): GET /tags with nested facets"
```

---

## Task 7: `GET /events?tag=&subtag=`

**Files:**
- Modify: `agentpit/api/routes/events.py`, `agentpit/services/event_service.py`
- Test: `tests/api/test_tags.py` (append)

**Interfaces:**
- Consumes: `TableRead.list_events_with_markets(..., tag, subtags)` (Task 5).
- Produces: `GET /events?limit=&offset=&category=&tag=&subtag=&subtag=` (`subtag` repeatable); `EventService.list_events_gamma(limit, offset, category=None, tag=None, subtags=None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_tags.py`:

```python
# ----- GET /events tag filtering ----------------------------------------------


def _event_slugs(response) -> set[str]:
    return {e["slug"] for e in response.json()}


def test_events_filters_by_tag(client):
    _seed({"a": ["politics", "trump"], "b": ["sports", "tennis"]})
    assert _event_slugs(client.get("/events?limit=10&tag=politics")) == {"a"}


def test_events_filters_by_repeated_subtag_ored(client):
    _seed(
        {
            "a": ["politics", "trump"],
            "b": ["politics", "midterms"],
            "c": ["politics", "iran"],
        }
    )
    got = _event_slugs(
        client.get("/events?limit=10&tag=politics&subtag=trump&subtag=midterms")
    )
    assert got == {"a", "b"}


def test_events_tag_is_case_insensitive(client):
    _seed({"a": ["politics"]})
    assert _event_slugs(client.get("/events?limit=10&tag=Politics")) == {"a"}


def test_events_blank_tag_does_not_collapse_the_page(client):
    _seed({"a": ["politics"], "b": ["sports"]})
    assert len(_event_slugs(client.get("/events?limit=10&tag=%20"))) == 2


def test_events_cache_does_not_serve_a_filtered_page_to_an_unfiltered_request(client):
    """The cache key must include the tag. Without it, the filtered page below
    would be served to the unfiltered request for up to one TTL."""
    _seed({"a": ["politics"], "b": ["sports"]})
    assert _event_slugs(client.get("/events?limit=10&offset=0&tag=politics")) == {"a"}
    assert len(_event_slugs(client.get("/events?limit=10&offset=0"))) == 2


def test_events_cache_distinguishes_subtag_sets(client):
    _seed({"a": ["politics", "trump"], "b": ["politics", "midterms"]})
    one = _event_slugs(client.get("/events?limit=10&offset=0&tag=politics&subtag=trump"))
    two = _event_slugs(
        client.get("/events?limit=10&offset=0&tag=politics&subtag=midterms")
    )
    assert one == {"a"}
    assert two == {"b"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_tags.py -q -k events`
Expected: FAIL — `test_events_filters_by_tag` returns both events (`tag` is ignored as an unknown query param).

- [ ] **Step 3: Widen the service method**

In `agentpit/services/event_service.py`, change `list_events_gamma` and `list_events` to accept and forward the two new arguments. `list_events_gamma` becomes:

```python
    def list_events_gamma(
        self,
        limit: int,
        offset: int,
        category: str | None = None,
        tag: str | None = None,
        subtags: list[str] | None = None,
    ) -> list[GammaEvent]:
```

and its `TableRead.list_events_with_markets(...)` call gains `tag=tag, subtags=subtags`. Apply the same two parameters and the same forwarding to `list_events`.

- [ ] **Step 4: Widen the route and its cache key**

In `agentpit/api/routes/events.py`, change the cache type annotation, `_list_events_cached` and the route.

The cache key type becomes a five-tuple:

```python
_events_cache: dict[
    tuple[int, int, str | None, str | None, tuple[str, ...]],
    tuple[float, list[GammaEvent]],
] = {}
```

`_list_events_cached` becomes:

```python
def _list_events_cached(
    service,
    *,
    limit: int,
    offset: int,
    category: str | None = None,
    tag: str | None = None,
    subtags: list[str] | None = None,
    now: float,
) -> list[GammaEvent]:
    """Return the cached page if it is younger than the TTL, else fetch + store.

    `now` is injected (monotonic seconds) so the TTL is deterministically
    testable. The sync `def` route runs in FastAPI's threadpool; dict get/set
    are atomic in CPython, so no lock is needed — a rare concurrent miss just
    does one extra harmless DB read.

    EVERY filter must be part of the key. A key missing `tag` would serve a
    filtered page to an unfiltered request (and the reverse) for up to one TTL.
    The subtag list is sorted into a tuple so `?subtag=a&subtag=b` and
    `?subtag=b&subtag=a` — the same OR set — share one entry.
    """
    normalized = category.strip() if category else None
    normalized_tag = tag.strip().lower() if tag else None
    normalized_subtags = tuple(
        sorted(s.strip().lower() for s in (subtags or []) if s and s.strip())
    )
    key = (limit, offset, normalized or None, normalized_tag, normalized_subtags)
    hit = _events_cache.get(key)
    if hit is not None and now - hit[0] < _EVENTS_TTL_S:
        return hit[1]
    result = service.list_events_gamma(
        limit=limit,
        offset=offset,
        category=normalized,
        tag=normalized_tag,
        subtags=list(normalized_subtags),
    )
    # Entries live 3s, so a plain flush at the cap is enough — no LRU needed.
    if len(_events_cache) >= _EVENTS_CACHE_MAX:
        _events_cache.clear()
    _events_cache[key] = (now, result)
    return result
```

The route becomes:

```python
@router.get("/events", response_model=list[GammaEvent])
def list_events(
    service: EventServiceDep,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
    tag: str | None = None,
    subtag: Annotated[list[str] | None, Query()] = None,
) -> list[GammaEvent]:
    return _list_events_cached(
        service,
        limit=limit,
        offset=offset,
        category=category,
        tag=tag,
        subtags=subtag,
        now=time.monotonic(),
    )
```

Add the imports this needs at the top of the file:

```python
from typing import Annotated

from fastapi import APIRouter, Query
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_tags.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. `tests/api/test_events_cache.py` exercises the cache whose key
just changed, but it calls `_list_events_cached(svc, limit=…, offset=…,
category=…, now=…)` with keyword arguments only and never builds a key tuple
itself, so the two new defaulted parameters leave it working untouched. If it
fails, the cause is a real behaviour change, not a mechanical one — read the
failure rather than editing the test to fit.

- [ ] **Step 7: Commit**

```bash
git add agentpit/api/routes/events.py agentpit/services/event_service.py tests/api/test_tags.py
git commit -m "feat(tags): tag and subtag filters on GET /events"
```

---

## Task 8: UI API client

**Files:**
- Create: `ui/src/api/tags.ts`, `ui/src/api/tags.test.ts`
- Modify: `ui/src/api/events.ts:16-22,41-66,77-97`

**Interfaces:**
- Consumes: `GET /tags`, `GET /events?tag=&subtag=` (Tasks 6, 7).
- Produces:
  - `ui/src/api/tags.ts`: `TagFacet`, `TagNavEntry`, `ListTagsResponse`, `listTags(): Promise<ListTagsResponse>`, `useTags()`.
  - `ui/src/api/events.ts`: `ListEventsParams` gains `tag?: string | undefined` and `subtags?: string[] | undefined`; `useEventsInfinite(tag: string | null, subtags?: string[])`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/api/tags.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listTags } from "./tags";
import { listEvents } from "./events";
import { apiFetch } from "@/api/client";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

describe("listTags", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset());

  it("requests /tags and returns the nested shape unchanged", async () => {
    const wire = {
      tags: [
        {
          slug: "politics",
          label: "Politics",
          count: 304,
          facets: [{ slug: "elections", label: "Elections", count: 161 }],
        },
      ],
    };
    vi.mocked(apiFetch).mockResolvedValueOnce(wire);
    await expect(listTags()).resolves.toEqual(wire);
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toBe("/tags");
  });
});

describe("listEvents tag params", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset().mockResolvedValue([]));

  function requestedPath(): string {
    return String(vi.mocked(apiFetch).mock.calls[0]?.[0]);
  }

  it("serialises tag", async () => {
    await listEvents({ limit: 20, offset: 0, tag: "politics" });
    expect(requestedPath()).toContain("tag=politics");
  });

  it("serialises each subtag as a repeated param", async () => {
    await listEvents({
      limit: 20,
      offset: 0,
      tag: "politics",
      subtags: ["trump", "midterms"],
    });
    const path = requestedPath();
    expect(path).toContain("subtag=trump");
    expect(path).toContain("subtag=midterms");
  });

  it("omits tag and subtag when absent or blank", async () => {
    await listEvents({ limit: 20, offset: 0, tag: "  ", subtags: [] });
    const path = requestedPath();
    expect(path).not.toContain("tag=");
    expect(path).not.toContain("subtag=");
  });

  it("still serialises category", async () => {
    await listEvents({ limit: 20, offset: 0, category: "Sports" });
    expect(requestedPath()).toContain("category=Sports");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `ui/`: `npx vitest run src/api/tags.test.ts`
Expected: FAIL — cannot resolve `./tags`.

- [ ] **Step 3: Write the tags client**

Create `ui/src/api/tags.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

/** A subcategory: a tag co-occurring with a top-level one. */
export interface TagFacet {
  slug: string;
  label: string;
  count: number;
}

/** A top-level category and the subcategories beneath it. */
export interface TagNavEntry {
  slug: string;
  label: string;
  count: number;
  facets: TagFacet[];
}

export interface ListTagsResponse {
  tags: TagNavEntry[];
}

export async function listTags(): Promise<ListTagsResponse> {
  return apiFetch<ListTagsResponse>("/tags");
}

export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: listTags,
    // The taxonomy only moves when the hourly sync runs, and the server caches
    // it for 30s anyway. Refetching on every mount buys nothing.
    staleTime: 60_000,
  });
}
```

- [ ] **Step 4: Widen the events client**

In `ui/src/api/events.ts`, extend `ListEventsParams`:

```ts
export interface ListEventsParams {
  limit: number;
  offset: number;
  /** Case-insensitive event category filter; omitted/blank means "all".
   *  Explicit `| undefined` because tsconfig sets exactOptionalPropertyTypes. */
  category?: string | undefined;
  /** Top-level tag slug; omitted/blank means "all". */
  tag?: string | undefined;
  /** Facet slugs, OR-ed among themselves and AND-ed with `tag`. */
  subtags?: string[] | undefined;
}
```

In `listEvents`, after the existing `category` block, add:

```ts
  if (params.tag && params.tag.trim()) {
    search.set("tag", params.tag.trim());
  }
  for (const subtag of params.subtags ?? []) {
    // Repeated key, not a comma-joined value — FastAPI reads `subtag` as a list.
    if (subtag.trim()) search.append("subtag", subtag.trim());
  }
```

Replace `useEventsInfinite` with:

```ts
export function useEventsInfinite(
  tag: string | null = null,
  subtags: string[] = [],
) {
  const normalizedTag = tag?.trim() || null;
  // Sorted so the same OR set in a different click order reuses one page chain
  // instead of refetching from scratch.
  const normalizedSubtags = [...subtags].map((s) => s.trim()).filter(Boolean).sort();
  return useInfiniteQuery({
    // The filters are part of the key so switching them starts a fresh page
    // chain instead of appending onto the previous filter's pages.
    queryKey: [
      "events",
      "infinite",
      EVENTS_PAGE_SIZE,
      normalizedTag,
      normalizedSubtags.join(","),
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listEvents({
        limit: EVENTS_PAGE_SIZE,
        offset: pageParam,
        tag: normalizedTag ?? undefined,
        subtags: normalizedSubtags,
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

Leave `listEventCategories` and `useEventCategories` in place — `?category=` and `/events/categories` both stay supported.

- [ ] **Step 5: Run the test to verify it passes**

Run from `ui/`: `npx vitest run src/api/tags.test.ts src/api/events.test.ts`
Expected: PASS.

- [ ] **Step 6: Verify the whole UI**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass. `typecheck` will FAIL on `MarketsPage.tsx` because `useEventsInfinite` changed shape — that is Task 9's job. If it does, complete Task 9 before committing this task, and commit the two together.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/tags.ts ui/src/api/tags.test.ts ui/src/api/events.ts
git commit -m "feat(tags): UI clients for /tags and the events tag filters"
```

---

## Task 9: Wire the sidebar to real tags

**Files:**
- Modify: `ui/src/pages/MarketsPage.tsx` (815 lines; the changes are confined to the constants block, the hook/state block, and the two places `getSubcategories` is called)

**Interfaces:**
- Consumes: `useTags()`, `TagNavEntry`, `TagFacet` (Task 8); `useEventsInfinite(tag, subtags)` (Task 8).
- Produces: nothing downstream.

**Constraint reminder:** the rendered markup must not change. Every `className`, every `<Button variant=…>`, the chevron, the mobile row, the `lg:grid-cols-[220px_minmax(0,1fr)]` sidebar — all identical. Only the values flowing into them change.

- [ ] **Step 1: Delete the hardcoded taxonomy**

Remove these top-level definitions entirely:

- `POLYMARKET_CATEGORY_ORDER`
- `buildCategoryList`
- `SubcategoryOption`
- `CATEGORY_SUBCATEGORIES`
- `getSubcategories`
- `eventMatchesKeywords`

Keep `normalizeCategoryKey` (still used for the expand/collapse state keys) and `getSubcategorySelectionKey`.

Remove the now-unused import of `useEventCategories` from `@/api/events`.

- [ ] **Step 2: Rekey the icon map by slug**

Replace `CATEGORY_ICONS` with a slug-keyed map covering the curated list. `getCategoryIcon` keeps its `Tag` fallback unchanged, so an uncovered slug still renders.

```tsx
const CATEGORY_ICONS: Record<string, LucideIcon> = {
  all: LayoutGrid,
  politics: Landmark,
  sports: Trophy,
  crypto: Bitcoin,
  elections: Landmark,
  geopolitics: Globe2,
  tennis: Trophy,
  esports: Gamepad2,
  soccer: Trophy,
  weather: CloudSun,
  tech: Cpu,
  "pop-culture": Clapperboard,
  finance: CircleDollarSign,
  economy: BriefcaseBusiness,
  world: Globe2,
  ai: Cpu,
  business: BriefcaseBusiness,
  science: FlaskConical,
};
```

Add `Gamepad2` and `CloudSun` to the existing `lucide-react` import.

- [ ] **Step 3: Swap the data source**

Replace the category/events hooks at the top of `MarketsPage`:

```tsx
  const { data: tagsData } = useTags();
  const navTags = useMemo<TagNavEntry[]>(() => tagsData?.tags ?? [], [tagsData]);

  // Selected values are SLUGS now, not display labels.
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedSubcategories, setSelectedSubcategories] = useState<string[]>([]);

  const facetsByCategory = useMemo(() => {
    const out = new Map<string, TagFacet[]>();
    for (const t of navTags) out.set(t.slug, t.facets);
    return out;
  }, [navTags]);

  // Bare facet slugs for the selected category, stripped of the "parent::"
  // scoping the selection state carries.
  const selectedFacetSlugs = useMemo(() => {
    if (!selectedCategory) return [];
    const prefix = `${normalizeCategoryKey(selectedCategory)}::`;
    return selectedSubcategories
      .filter((key) => key.startsWith(prefix))
      .map((key) => key.slice(prefix.length));
  }, [selectedCategory, selectedSubcategories]);

  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useEventsInfinite(selectedCategory, selectedFacetSlugs);
```

Add the import: `import { useTags, type TagFacet, type TagNavEntry } from "@/api/tags";`

Replace `categoriesWithAll` so the sidebar loop still receives one array. Because entries are now objects, use a sentinel for "All":

```tsx
  const ALL_TAB: TagNavEntry = {
    slug: "all",
    label: "All",
    count: 0,
    facets: [],
  };
  const categoriesWithAll = useMemo<TagNavEntry[]>(
    () => [ALL_TAB, ...navTags],
    [navTags],
  );
```

- [ ] **Step 4: Update the two render loops**

In BOTH the mobile row and the desktop `<aside>`, the loop variable becomes a `TagNavEntry`. The changes are mechanical and identical in shape:

- `categoriesWithAll.map((category) => {` becomes `categoriesWithAll.map((entry) => {`
- `const isAll = category === "All";` becomes `const isAll = entry.slug === "all";`
- `selectedCategory === category` becomes `selectedCategory === entry.slug`
- `getCategoryIcon(category)` becomes `getCategoryIcon(entry.slug)`
- `handleCategorySelect(isAll ? null : category)` becomes `handleCategorySelect(isAll ? null : entry.slug)`
- `key={category}` becomes `key={entry.slug}`
- the rendered text `{category}` becomes `{entry.label}` (and `<span className="truncate">{category}</span>` becomes `<span className="truncate">{entry.label}</span>`)
- `const subcategories = isAll ? [] : getSubcategories(category);` becomes `const subcategories = isAll ? [] : entry.facets;`
- `normalizeCategoryKey(category)` becomes `normalizeCategoryKey(entry.slug)`

Inside the subcategory loops, the item is a `TagFacet`:

- `subcategories.map((subcategory) => {` keeps its name; `subcategory.id` becomes `subcategory.slug` in `getSubcategorySelectionKey(...)` and in `key={...}`
- `{subcategory.label}` is unchanged — `TagFacet` has a `label` too
- `handleSubcategoryToggle(category, subcategory.id)` becomes `handleSubcategoryToggle(entry.slug, subcategory.slug)`

In the mobile subcategory block, `getSubcategories(selectedCategory)` becomes `facetsByCategory.get(selectedCategory) ?? []` — twice, once for the chevron's visibility test and once for the list.

**Do not** add `subcategory.count` or `entry.count` to the markup.

- [ ] **Step 5: Drop the client-side subcategory filter**

In the `filtered` memo, delete the `withSubcategories` block and its `selectedSubcategoryOptions` dependency — subcategory filtering is a server query now. `queryFiltered` feeds `sorted` directly:

```tsx
    const sorted = [...queryFiltered];
```

Delete the `selectedSubcategoryOptions` memo entirely.

Narrow the eager-paging flag, since search is now the only client-side filter left:

```tsx
  const isSearching = trimmedQuery.length > 0;
  const hasClientSideFilter = isSearching;
```

- [ ] **Step 6: Verify the UI**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass. `typecheck` is the real gate here — there is no way to render `MarketsPage` in a test, because vitest runs in the node environment and `@testing-library/react` is not installed.

- [ ] **Step 7: Verify against a running stack by eye**

Start the API and the UI, open the markets page, and confirm:

1. The sidebar lists roughly sixteen categories, `Politics` first.
2. Expanding `Politics` shows about twenty subcategories (`Elections`, `US Election`, `Geopolitics`, `Trump`, `Midterms`, …), not three.
3. Clicking a subcategory narrows the grid, and the network tab shows one request carrying `?tag=politics&subtag=…` — not a burst of page fetches.
4. Nothing on the page has moved, resized or changed colour.

- [ ] **Step 8: Commit**

```bash
git add ui/src/pages/MarketsPage.tsx
git commit -m "feat(tags): markets sidebar reads the real tag taxonomy"
```

---

## Task 10: Full verification

**Files:** none — this task only runs and reports.

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Do NOT source `.env` first.

- [ ] **Step 2: UI suite**

Run from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 3: Confirm the deletions actually landed**

```bash
grep -rn "CATEGORY_SUBCATEGORIES\|eventMatchesKeywords\|buildCategoryList\|POLYMARKET_CATEGORY_ORDER" ui/src/
```
Expected: no output. Any hit means dead code survived Task 9.

- [ ] **Step 4: Confirm what deliberately survived**

```bash
grep -rn "resolve_category\|category_rank" agentpit/ | grep -v ".pyc"
grep -n "def list_event_categories" agentpit/db/table_read.py
```
Expected: both still present. `CATEGORY` and its resolver stay for the local-market creation path and `EventDetailPage`'s badge; removing them is out of scope.

- [ ] **Step 5: Report**

State the backend test count, the UI test count, and the result of Steps 3 and 4. If anything failed, report the actual output rather than a summary.

---

## Self-Review

**Spec coverage.** Every section of `2026-08-06-tag-taxonomy-design.md` maps to a task: Data model → 2; Sync write path → 3; Taxonomy constants → 1; Read path → 4 and 5; API → 6 and 7; UI → 8 and 9; Testing → each task's own steps plus 10; Rollout → needs no code (the sync runs on boot before its first sleep); Non-goals → the Global Constraints block and Task 9's reminder.

**Placeholders.** None. Every code step carries the actual code; every test step carries the actual assertions.

**Type consistency.** `replace_market_tags(market_id, tags: list[tuple[str, str]])` in Task 2 is what Task 3 calls. `list_tag_nav` / `list_tag_facets` return `list[tuple[str, str, int]]` in Task 4 and are unpacked as `slug, label, count` in Task 6. `TagNavEntry.facets: list[TagFacet]` in Task 6 matches the TypeScript interface in Task 8, which Task 9 consumes as `entry.facets`. `useEventsInfinite(tag, subtags)` is defined in Task 8 and called with exactly that arity in Task 9.

**Known coupling.** Task 8 changes `useEventsInfinite`'s signature, which breaks `MarketsPage.tsx` until Task 9 lands. Task 8's Step 6 says so and instructs committing the pair together if typecheck fails. This is deliberate: splitting them would mean either a throwaway shim or one very large task.
