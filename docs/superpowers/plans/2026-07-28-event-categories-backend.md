# Event Categories Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `events.CATEGORY` from Polymarket tag data so the category filter already shipped in the UI on the `categories-added` branch returns real events instead of an empty list.

**Architecture:** A new pure module reduces a market's Polymarket tag slugs to one of eight canonical categories using a priority-ordered lookup plus an alias fallback. The existing Gamma fetch gains one query parameter (`include_tag=true`) so tags arrive inline at no extra request cost. The sync writes the resolved category when it creates an event, and raises an existing event's category when a member market resolves to a stricter one.

**Tech Stack:** Python 3, FastAPI, sqlite3 (raw SQL, no ORM), pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-event-categories-backend-design.md`

## Global Constraints

- Run tests with `.venv/bin/python -m pytest`. **Never** source `.env` into pytest — it defeats the `os.environ.setdefault` calls in `tests/conftest.py` and causes live-sync flakes.
- Do **not** change the database schema. `CATEGORY TEXT` already exists in `agentpit/db/table_create.py:187`.
- Category values written to the database must be exactly one of: `Sports`, `Crypto`, `Science`, `Technology`, `Pop Culture`, `Business`, `World`, `Politics` — or `NULL`. These strings must match `POLYMARKET_CATEGORY_ORDER` in `ui/src/pages/MarketsPage.tsx:31-40` verbatim, or the UI renders duplicate category tabs.
- Omit the `Co-Authored-By: Claude` trailer from commit messages.
- Tests already on this branch must stay green: `tests/api/test_events.py`, `tests/services/test_event_service.py`, `tests/db/test_events_dal.py`.

## File Structure

| File | Responsibility |
|---|---|
| `agentpit/polymarket/category_resolver.py` (create) | Pure tag-slug → category reduction. No network, no database. |
| `tests/polymarket/test_category_resolver.py` (create) | Unit tests for the above. |
| `agentpit/db/table_write.py` (modify) | Add `update_event_category` — a targeted single-column write. |
| `agentpit/db/table_read.py` (modify) | Make the category filter case-insensitive. |
| `tests/db/test_events_dal.py` (modify) | Cover the new write and the case-insensitive filter. |
| `agentpit/polymarket/polymarket_sync.py` (modify) | Request tags, derive category from them, propagate to existing events. |
| `tests/polymarket/test_polymarket_event_capture.py` (modify) | Cover metadata extraction and event-category propagation. |
| `tests/polymarket/test_polymarket_sync.py` (modify) | Cover the `include_tag=true` query parameter. |

---

### Task 1: Category resolver

**Files:**
- Create: `agentpit/polymarket/category_resolver.py`
- Test: `tests/polymarket/test_category_resolver.py`

**Interfaces:**
- Consumes: nothing — this module has no internal dependencies.
- Produces:
  - `CATEGORY_PRIORITY: tuple[str, ...]` — the eight categories, strictest first.
  - `resolve_category(tag_slugs: Iterable[str | None]) -> str | None`
  - `category_rank(category: str | None) -> int` — lower is stricter; unknown and `None` sort last.

**Background for the implementer:** Polymarket's Gamma API has a `category` field on every market and event, but it is `null` for all of them — dead weight from an older schema. The live taxonomy is `tags`, a flat unordered list mixing top-level categories (`politics`, `crypto`) with fine-grained topics (`macron`, `etf`, `gta-vi`). Because the list is unordered, picking the first recognised tag would assign the same market different categories on different sync passes; the resolver must therefore pick by a fixed priority instead.

- [ ] **Step 1: Write the failing tests**

Create `tests/polymarket/test_category_resolver.py`:

```python
"""Unit tests for reducing Polymarket tag slugs to a single category."""

from __future__ import annotations

from agentpit.polymarket.category_resolver import (
    CATEGORY_PRIORITY,
    category_rank,
    resolve_category,
)


def test_resolves_exact_canonical_slug():
    assert resolve_category(["sports"]) == "Sports"
    assert resolve_category(["crypto"]) == "Crypto"
    assert resolve_category(["politics"]) == "Politics"


def test_normalises_upstream_labels_to_ui_names():
    """Upstream labels `pop-culture` "Culture" and `technology` lowercase.

    buildCategoryList() in MarketsPage.tsx matches on these exact strings and
    renders anything unrecognised as an extra tab.
    """
    assert resolve_category(["pop-culture"]) == "Pop Culture"
    assert resolve_category(["technology"]) == "Technology"
    assert resolve_category(["tech"]) == "Technology"


def test_priority_beats_input_order():
    """Gamma returns tags unordered, so the result must not depend on order."""
    assert resolve_category(["politics", "world"]) == "World"
    assert resolve_category(["world", "politics"]) == "World"


def test_canonical_tag_beats_higher_priority_alias():
    """`weather` aliases to Science (rank 2), `politics` is canonical (rank 7).

    The alias map is a heuristic and must never override Polymarket's own
    top-level labelling.
    """
    assert resolve_category(["politics", "weather"]) == "Politics"


def test_alias_pass_runs_only_when_no_canonical_tag_matched():
    assert resolve_category(["geopolitics", "iran", "trump-iran"]) == "World"
    assert resolve_category(["fed", "economy", "jerome-powell"]) == "Business"
    assert resolve_category(["weather", "daily-temperature"]) == "Science"


def test_alias_pass_also_honours_priority():
    """geopolitics -> World (rank 6), weather -> Science (rank 2)."""
    assert resolve_category(["geopolitics", "weather"]) == "Science"


def test_returns_none_when_nothing_matches():
    assert resolve_category([]) is None
    assert resolve_category(["macron", "resign", "gta-vi"]) is None


def test_ignores_empty_and_none_slugs():
    assert resolve_category([None, "", "   "]) is None
    assert resolve_category([None, "sports", ""]) == "Sports"


def test_slugs_are_case_and_whitespace_insensitive():
    assert resolve_category(["  SPORTS  "]) == "Sports"
    assert resolve_category(["Pop-Culture"]) == "Pop Culture"


def test_category_rank_orders_priority_strictest_first():
    ranks = [category_rank(c) for c in CATEGORY_PRIORITY]
    assert ranks == sorted(ranks)
    assert category_rank("Sports") < category_rank("Politics")


def test_category_rank_sinks_unknown_and_none_to_last():
    assert category_rank(None) == len(CATEGORY_PRIORITY)
    assert category_rank("Handmade Category") == len(CATEGORY_PRIORITY)
    assert category_rank("Politics") < category_rank(None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/polymarket/test_category_resolver.py -v`

Expected: collection error — `ModuleNotFoundError: No module named 'agentpit.polymarket.category_resolver'`.

- [ ] **Step 3: Write the implementation**

Create `agentpit/polymarket/category_resolver.py`:

```python
"""Reduce Polymarket tag slugs to the categories the UI filters by.

Polymarket's own ``category`` field is dead — every market and every nested
event returns ``null``. The live taxonomy is ``tags[]``, a flat unordered list
mixing top-level categories ("Politics", "Crypto") with fine-grained topics
("Macron", "ETF", "GTA VI"). This module reduces that list to one category.
"""

from __future__ import annotations

from typing import Iterable

# Ordered strictest-first: a narrower category wins when a market carries
# several. "Politics" is last because Polymarket tags most geopolitics with it
# on top of the more specific "World" — 109 of 500 sampled markets, including
# every non-US election. Polymarket's own UI files those under World.
CATEGORY_PRIORITY: tuple[str, ...] = (
    "Sports",
    "Crypto",
    "Science",
    "Technology",
    "Pop Culture",
    "Business",
    "World",
    "Politics",
)

# Polymarket's top-level tag slugs. Values are normalised to the labels the UI
# expects, not the labels upstream returns: `pop-culture` is labelled "Culture"
# and `technology` is lowercase, and buildCategoryList() in MarketsPage.tsx
# would render either as a duplicate tab.
_CANONICAL_SLUGS: dict[str, str] = {
    "sports": "Sports",
    "crypto": "Crypto",
    "science": "Science",
    "technology": "Technology",
    "tech": "Technology",
    "pop-culture": "Pop Culture",
    "business": "Business",
    "world": "World",
    "politics": "Politics",
}

# Second-chance map for the ~5% of markets Polymarket never tagged with a
# top-level category — mostly geopolitics and macro. Recovers all but ~0.4%.
# Consulted only when no canonical tag matched.
_ALIAS_SLUGS: dict[str, str] = {
    "geopolitics": "World",
    "middle-east": "World",
    "war": "World",
    "elections": "Politics",
    "finance": "Business",
    "economy": "Business",
    "economic-policy": "Business",
    "fed": "Business",
    "earnings": "Business",
    "oil": "Business",
    "inflation": "Business",
    "weather": "Science",
    "pandemics": "Science",
    "health": "Science",
    "space": "Science",
    "ai": "Technology",
}

_UNRANKED = len(CATEGORY_PRIORITY)


def category_rank(category: str | None) -> int:
    """Position in ``CATEGORY_PRIORITY`` — lower is stricter.

    ``None`` and any value outside the tuple (e.g. a free-form category from
    ``POST /markets``) sort last, so a resolved category always outranks them.
    """
    if category is None:
        return _UNRANKED
    try:
        return CATEGORY_PRIORITY.index(category)
    except ValueError:
        return _UNRANKED


def _strictest(candidates: set[str]) -> str | None:
    if not candidates:
        return None
    return min(candidates, key=category_rank)


def resolve_category(tag_slugs: Iterable[str | None]) -> str | None:
    """Reduce a market's tag slugs to one category, or ``None``.

    Deterministic regardless of input order: Gamma returns ``tags[]`` unordered,
    so picking the first recognised slug would categorize the same market
    differently across sync passes.

    An exact canonical tag always beats an alias, even a stricter one — the
    alias map is a heuristic and must not override Polymarket's own labelling.
    """
    normalized = {s.strip().lower() for s in tag_slugs if s and s.strip()}
    canonical = {_CANONICAL_SLUGS[s] for s in normalized if s in _CANONICAL_SLUGS}
    if canonical:
        return _strictest(canonical)
    return _strictest({_ALIAS_SLUGS[s] for s in normalized if s in _ALIAS_SLUGS})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/polymarket/test_category_resolver.py -v`

Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add agentpit/polymarket/category_resolver.py tests/polymarket/test_category_resolver.py
git commit -m "Add Polymarket tag-to-category resolver"
```

---

### Task 2: Database layer — targeted category write and case-insensitive filter

**Files:**
- Modify: `agentpit/db/table_write.py` (add a method after `attach_market_to_event`, which ends at line 222)
- Modify: `agentpit/db/table_read.py:374` (the `where` clause inside `list_events_with_markets`)
- Test: `tests/db/test_events_dal.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `TableWrite.update_event_category(db: sqlite3.Connection, *, event_id: int, category: str) -> None` — used by Task 4.

**Background for the implementer:** `tests/db/test_events_dal.py` already has a module-level `db` fixture (an in-memory sqlite connection with all tables created) and a `_make_market(db, *, question, cond_id, event_id=None)` helper. Reuse them; do not redefine them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_events_dal.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/db/test_events_dal.py -v -k "update_event_category or case_insensitively"`

Expected: the two `update_event_category` tests FAIL with `AttributeError: type object 'TableWrite' has no attribute 'update_event_category'`; the case-insensitivity test FAILS with `assert 0 == 1`.

- [ ] **Step 3: Add the write method**

In `agentpit/db/table_write.py`, insert after `attach_market_to_event` (which ends at line 222) and before `create_market`:

```python
    @staticmethod
    def update_event_category(
        db: sqlite3.Connection, *, event_id: int, category: str
    ) -> None:
        """Set an event's category, leaving every other column alone.

        Deliberately not routed through ``upsert_event``: that matches on SLUG,
        but the sync finds already-known events by POLYMARKET_EVENT_ID. If
        upstream renamed the slug, a full upsert would insert a duplicate row
        instead of updating the existing one.
        """
        db.execute(
            "UPDATE events SET CATEGORY = ? WHERE EVENT_ID = ?",
            (category, event_id),
        )
```

- [ ] **Step 4: Make the filter case-insensitive**

In `agentpit/db/table_read.py`, inside `list_events_with_markets`, change line 374 from:

```python
            where = " WHERE CATEGORY = ?"
```

to:

```python
            # NOCASE so a case drift between the label the UI sends and the
            # label stored can't silently return an empty page.
            where = " WHERE CATEGORY = ? COLLATE NOCASE"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/db/test_events_dal.py -v`

Expected: PASS — the whole file, including the category tests already on the branch.

- [ ] **Step 6: Commit**

```bash
git add agentpit/db/table_write.py agentpit/db/table_read.py tests/db/test_events_dal.py
git commit -m "Add targeted event-category write and case-insensitive category filter"
```

---

### Task 3: Request tags from Gamma and derive the category from them

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` — imports (around line 24), `fetch_all_polymarket_markets` (lines 205-220), `_extract_event_metadata` (lines 361-389)
- Test: `tests/polymarket/test_polymarket_event_capture.py` (modify one existing test, append three)
- Test: `tests/polymarket/test_polymarket_sync.py` (append one)

**Interfaces:**
- Consumes: `resolve_category` from Task 1.
- Produces: `_extract_event_metadata(pm_market: dict) -> dict | None` — signature unchanged; its `"category"` key is now derived from `pm_market["tags"]` rather than from the nested event object. Task 4 consumes that key.

**Background for the implementer:** `fetch_all_polymarket_markets` builds its query string from a `query_parts` list at lines 205-220. Without `include_tag=true`, every market in the response has `tags: null` — verified against the live API. The nested `events[]` objects inside a `/markets` response carry no `tags` key at all, which is why the category has to come from the market level.

One existing test asserts the old, dead behaviour and must be rewritten in Step 1 — this is expected, not a regression.

- [ ] **Step 1: Rewrite the existing test that asserts the dead field**

In `tests/polymarket/test_polymarket_event_capture.py`, replace `test_extract_event_metadata_pulls_first_event` in full. The nested `"category": "Sports"` is removed (upstream always sends `null` there) and a market-level `tags` list takes over as the source:

```python
def test_extract_event_metadata_pulls_first_event():
    pm = {
        # Category comes from the market's own tags — the nested event object
        # carries no tags, and its `category` field is null upstream.
        "tags": [{"id": "1", "label": "Sports", "slug": "sports"}],
        "events": [
            {
                "id": "evt-1",
                "slug": "2026-fifa-world-cup-winner",
                "title": "2026 FIFA World Cup Winner",
                "description": "Who lifts the cup?",
                "image": "https://img/wc.png",
                "startDate": "2026-06-11T00:00:00Z",
                "endDate": "2026-07-19T22:00:00Z",
            }
        ],
    }
    meta = _extract_event_metadata(pm)
    assert meta is not None
    assert meta["slug"] == "2026-fifa-world-cup-winner"
    assert meta["title"] == "2026 FIFA World Cup Winner"
    assert meta["polymarket_event_id"] == "evt-1"
    assert meta["icon_url"] == "https://img/wc.png"
    assert meta["category"] == "Sports"
    # Dates are converted to unix int when parseable.
    assert isinstance(meta["start_date"], int)
    assert isinstance(meta["end_date"], int)
```

Then append these three tests to the same `_extract_event_metadata` section (immediately after `test_extract_event_metadata_handles_missing_optional_fields`):

```python
def test_extract_event_metadata_ignores_the_dead_nested_category_field():
    """Gamma returns `category: null` on every nested event.

    If it ever starts returning a value, the tag-derived category still wins —
    tags are the taxonomy Polymarket actually maintains.
    """
    pm = {
        "tags": [{"slug": "crypto"}],
        "events": [{"id": "x", "slug": "x", "title": "X", "category": "Sports"}],
    }
    meta = _extract_event_metadata(pm)
    assert meta is not None
    assert meta["category"] == "Crypto"


def test_extract_event_metadata_survives_malformed_tags():
    pm = {
        "tags": [None, "not-a-dict", {"slug": None}, {}, {"slug": "sports"}],
        "events": [{"id": "x", "slug": "x", "title": "X"}],
    }
    meta = _extract_event_metadata(pm)
    assert meta is not None
    assert meta["category"] == "Sports"


def test_extract_event_metadata_category_is_none_without_recognisable_tags():
    pm = {
        "tags": [{"slug": "gta-vi"}, {"slug": "all"}],
        "events": [{"id": "x", "slug": "x", "title": "X"}],
    }
    meta = _extract_event_metadata(pm)
    assert meta is not None
    assert meta["category"] is None
```

Append to `tests/polymarket/test_polymarket_sync.py` (this test stubs the HTTP call, so it needs neither anvil nor the network):

```python
def test_fetch_all_polymarket_markets_requests_tags(monkeypatch):
    """Without include_tag=true every market comes back with `tags: null`."""
    from agentpit.polymarket import polymarket_sync

    seen: list[str] = []

    def fake_get(url: str):
        seen.append(url)
        return []

    monkeypatch.setattr(polymarket_sync, "get", fake_get)
    polymarket_sync.fetch_all_polymarket_markets(host="https://gamma.test")

    assert seen
    assert "include_tag=true" in seen[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
.venv/bin/python -m pytest tests/polymarket/test_polymarket_event_capture.py -v \
  && .venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py::test_fetch_all_polymarket_markets_requests_tags -v
```

Expected: `test_extract_event_metadata_pulls_first_event` FAILS with `assert None == 'Sports'`; `test_extract_event_metadata_ignores_the_dead_nested_category_field` FAILS with `assert 'Sports' == 'Crypto'`; `test_extract_event_metadata_survives_malformed_tags` FAILS with `assert None == 'Sports'`; `test_fetch_all_polymarket_markets_requests_tags` FAILS with `assert 'include_tag=true' in '...'`.

- [ ] **Step 3: Import the resolver**

In `agentpit/polymarket/polymarket_sync.py`, add to the import block near line 24 (next to the other `agentpit` imports):

```python
from agentpit.polymarket.category_resolver import resolve_category
```

- [ ] **Step 4: Request tags in the Gamma query**

In `fetch_all_polymarket_markets`, after the `closed` handling and immediately before `base_query = "&".join(query_parts)` (line 220), add:

```python
    # Tags are the only live source of category on Gamma: the `category` field
    # is null for every market, and the nested `events[]` objects carry no tags
    # at all. Without this parameter each market comes back with `tags: null`.
    query_parts.append("include_tag=true")
```

- [ ] **Step 5: Derive the category from the market's tags**

In `_extract_event_metadata`, update the docstring and the `category` entry. The docstring currently reads "Pull event fields from the upstream `events` array." — extend it, then change the returned dict.

Replace:

```python
        "category": raw.get("category"),
```

with:

```python
        # NOT raw.get("category") — that field is null on every Gamma response.
        # Tags live on the market, not on the nested event object.
        "category": resolve_category(
            t.get("slug")
            for t in (pm_market.get("tags") or [])
            if isinstance(t, dict)
        ),
```

And add this paragraph to the function's docstring, after the existing text:

```
    The category is derived from the *market's* ``tags`` rather than from the
    nested event: Gamma's ``category`` field is null everywhere, and the nested
    event objects carry no tags.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:
```bash
.venv/bin/python -m pytest tests/polymarket/test_polymarket_event_capture.py tests/polymarket/test_polymarket_sync.py::test_fetch_all_polymarket_markets_requests_tags -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_polymarket_event_capture.py tests/polymarket/test_polymarket_sync.py
git commit -m "Derive event category from Polymarket market tags"
```

---

### Task 4: Categorize events that already exist locally

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` — imports, and `bind_market_to_upstream_event` (lines 423-455)
- Test: `tests/polymarket/test_polymarket_event_capture.py` (append)

**Interfaces:**
- Consumes: `category_rank` from Task 1, `TableWrite.update_event_category` from Task 2, the `"category"` key produced by Task 3.
- Produces: nothing consumed by later tasks.

**Background for the implementer:** `bind_market_to_upstream_event` currently does `event = existing or TableWrite.upsert_event(...)`. When the event is already known — matched by `POLYMARKET_EVENT_ID` — the upsert is skipped entirely, so no field is ever refreshed. Without this task, only events created *after* Task 3 ships would ever get a category; every event already in the database would stay `NULL` forever.

An event owns many markets, and the sync's iteration order across them is not guaranteed. A last-writer-wins update would let an event's category oscillate between sync passes. Comparing ranks instead makes the outcome order-independent: the event converges on the strictest category any member market resolves to.

- [ ] **Step 1: Write the failing tests**

Append to `tests/polymarket/test_polymarket_event_capture.py`, in the `bind_market_to_upstream_event` section:

```python
def test_bind_market_sets_category_on_a_new_event(db):
    market = _seed_market(db, question="will france win?", cond_id=_hex32("fr"))
    pm = {
        "tags": [{"slug": "sports"}],
        "events": [{"id": "evt-1", "slug": "wc", "title": "WC"}],
    }

    bind_market_to_upstream_event(db, market, pm)

    event = TableRead.get_event_by_slug(db, "wc")
    assert event is not None and event.category == "Sports"


def test_bind_market_upgrades_an_existing_event_to_a_stricter_category(db):
    """Sibling markets resolve independently; the strictest one wins."""
    m1 = _seed_market(db, question="france?", cond_id=_hex32("fr"))
    m2 = _seed_market(db, question="spain?", cond_id=_hex32("es"))
    pm_events = [{"id": "evt-1", "slug": "wc", "title": "WC"}]

    bind_market_to_upstream_event(
        db, m1, {"events": pm_events, "tags": [{"slug": "politics"}]}
    )
    bind_market_to_upstream_event(
        db, m2, {"events": pm_events, "tags": [{"slug": "sports"}]}
    )

    event = TableRead.get_event_by_slug(db, "wc")
    assert event is not None and event.category == "Sports"


def test_bind_market_does_not_downgrade_an_existing_event_category(db):
    """Same pair as above in the opposite order — the result must not change."""
    m1 = _seed_market(db, question="france?", cond_id=_hex32("fr"))
    m2 = _seed_market(db, question="spain?", cond_id=_hex32("es"))
    pm_events = [{"id": "evt-1", "slug": "wc", "title": "WC"}]

    bind_market_to_upstream_event(
        db, m1, {"events": pm_events, "tags": [{"slug": "sports"}]}
    )
    bind_market_to_upstream_event(
        db, m2, {"events": pm_events, "tags": [{"slug": "politics"}]}
    )

    event = TableRead.get_event_by_slug(db, "wc")
    assert event is not None and event.category == "Sports"


def test_bind_market_never_clears_a_stored_category(db):
    """An unresolvable market must not undo a sibling's categorization."""
    m1 = _seed_market(db, question="france?", cond_id=_hex32("fr"))
    m2 = _seed_market(db, question="spain?", cond_id=_hex32("es"))
    pm_events = [{"id": "evt-1", "slug": "wc", "title": "WC"}]

    bind_market_to_upstream_event(
        db, m1, {"events": pm_events, "tags": [{"slug": "sports"}]}
    )
    bind_market_to_upstream_event(
        db, m2, {"events": pm_events, "tags": [{"slug": "gta-vi"}]}
    )

    event = TableRead.get_event_by_slug(db, "wc")
    assert event is not None and event.category == "Sports"


def test_bind_existing_market_categorizes_a_previously_uncategorized_event(db):
    """The backfill path: an event synced before this feature acquires its
    category on the next sync pass, with no migration script."""
    market = _seed_market_with_polymarket_id(
        db, question="france?", cond_id=_hex32("fr"), polymarket_id=99
    )
    pm_events = [{"id": "evt-1", "slug": "wc", "title": "WC"}]
    # First pass: no tags at all, as before this feature shipped.
    bind_market_to_upstream_event(db, market, {"events": pm_events})
    assert TableRead.get_event_by_slug(db, "wc").category is None

    # Second pass: same event, now with tags.
    bind_existing_market_to_upstream_event(
        db,
        polymarket_id=99,
        pm_market={"events": pm_events, "tags": [{"slug": "sports"}]},
    )

    event = TableRead.get_event_by_slug(db, "wc")
    assert event is not None and event.category == "Sports"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_event_capture.py -v -k "category"`

Expected: `test_bind_market_sets_category_on_a_new_event` PASSES already (Task 3 covers the create path). The other four FAIL with `assert None == 'Sports'` or `assert 'Politics' == 'Sports'`.

- [ ] **Step 3: Add the imports**

In `agentpit/polymarket/polymarket_sync.py`, extend the resolver import added in Task 3 and add the `Event` type:

```python
from agentpit.polymarket.category_resolver import category_rank, resolve_category
from agentpit.datastructures.event import Event
```

- [ ] **Step 4: Add the merge helper**

In `agentpit/polymarket/polymarket_sync.py`, add this function immediately before `bind_market_to_upstream_event` (line 423):

```python
def _sync_event_category(db: Connection, event: Event, category: str | None) -> None:
    """Raise an event's category when ``category`` is stricter than what's stored.

    An event owns many markets and the sync's order across them isn't
    guaranteed, so last-writer-wins would let the category oscillate between
    passes. Comparing ranks makes the result order-independent: the event
    converges on the strictest category any member market resolves to.

    Never clears — a market whose tags resolve to nothing (~0.4% of the feed)
    must not undo a good categorization contributed by a sibling market.
    """
    if category is None:
        return
    if category_rank(category) >= category_rank(event.category):
        return
    TableWrite.update_event_category(db, event_id=event.event_id, category=category)
```

- [ ] **Step 5: Call it on the already-known-event path**

In `bind_market_to_upstream_event`, replace:

```python
    event = existing or TableWrite.upsert_event(
        db,
        slug=meta["slug"],
        title=meta["title"],
        description=meta["description"],
        icon_url=meta["icon_url"],
        category=meta["category"],
        start_date=meta["start_date"],
        end_date=meta["end_date"],
        polymarket_event_id=meta["polymarket_event_id"],
    )
```

with:

```python
    if existing is not None:
        # The upsert is skipped for known events (it matches on SLUG, which
        # upstream can rename), so the category is refreshed on its own.
        event = existing
        _sync_event_category(db, event, meta["category"])
    else:
        event = TableWrite.upsert_event(
            db,
            slug=meta["slug"],
            title=meta["title"],
            description=meta["description"],
            icon_url=meta["icon_url"],
            category=meta["category"],
            start_date=meta["start_date"],
            end_date=meta["end_date"],
            polymarket_event_id=meta["polymarket_event_id"],
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_event_capture.py -v`

Expected: PASS, whole file.

- [ ] **Step 7: Run the full affected suite**

Run:
```bash
.venv/bin/python -m pytest tests/polymarket/test_category_resolver.py \
  tests/polymarket/test_polymarket_event_capture.py \
  tests/db/test_events_dal.py \
  tests/services/test_event_service.py \
  tests/api/test_events.py -v
```

Expected: PASS. Do **not** source `.env` first.

- [ ] **Step 8: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_polymarket_event_capture.py
git commit -m "Categorize already-synced events on subsequent sync passes"
```

---

### Task 5: Verify end-to-end against the live feed

**Files:** none — this task changes no code. It confirms the pipeline produces real categories rather than an empty list.

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing.

**Background for the implementer:** Tasks 1-4 are unit-tested against synthetic tag payloads. This task checks the assumption those tests rest on — that the live Gamma feed actually returns the tags we ask for, and that they resolve to a sensible spread of categories. It needs the network but neither anvil nor the database.

- [ ] **Step 1: Resolve categories over a live sample**

Run:

```bash
.venv/bin/python -c "
import json, urllib.request
from agentpit.polymarket.category_resolver import resolve_category
from collections import Counter

req = urllib.request.Request(
    'https://gamma-api.polymarket.com/markets'
    '?limit=100&closed=false&active=true&archived=false&include_tag=true'
    '&order=volumeNum&ascending=false',
    headers={'User-Agent': 'agentpit-verify'},
)
markets = json.load(urllib.request.urlopen(req))
counts = Counter(
    resolve_category(t.get('slug') for t in (m.get('tags') or []))
    for m in markets
)
print('markets:', len(markets))
for cat, n in counts.most_common():
    print(f'  {cat!s:<12} {n}')
"
```

Expected: 100 markets, a spread across several named categories, and at most a handful resolving to `None`. If **every** market resolves to `None`, `include_tag=true` did not reach the request — recheck Task 3 Step 4.

- [ ] **Step 2: Record the result**

No commit. Report the category distribution in the task summary so the reviewer can confirm the spread looks plausible (Politics and Sports should dominate; `None` should be in the low single digits).

---

## Notes for the reviewer

- **No schema migration and no backfill script.** `_polymarket_sync_loop` in `agentpit/api/app.py:62-73` re-binds every market on every pass, so Task 4 fills in existing events on the next tick.
- **Known limitation, deliberately not fixed** (documented in the spec): if an event exists under a given `SLUG` but has no `POLYMARKET_EVENT_ID`, the `existing` lookup misses, the create branch runs, and `upsert_event`'s UPDATE overwrites `CATEGORY` — possibly with `None`. This affects every column the upsert touches, predates this work, and is reachable only for markets that resolve to nothing. Fixing it would mean changing `upsert_event` semantics, which the seeder in `scripts/seed_world_cup_event.py` also depends on.
- **Out of scope:** the subcategory chips in `MarketsPage.tsx` stay client-side keyword matching; no `event_tags` table; no validation of the free-form `category` accepted by `POST /markets`.
- **Unrelated, flagged for merge time:** this branch's `ui/src/components/TopNav.tsx` reverts `useTheme` back to `getResolvedTheme`/`setTheme`, which appears to undo commit `15a6bf4`.
