# Event categories on the backend

Populate `events.CATEGORY` so the category filter the UI already ships on the
`categories-added` branch returns actual events instead of an empty list.

## Problem

The branch added the whole API surface for category filtering — `GET /events?category=`,
`GET /events/categories`, the `WHERE CATEGORY = ?` clause in
`TableRead.list_events_with_markets`, and the `ListEventCategoriesResponse` model.
None of it works, because `events.CATEGORY` is always `NULL`.

Two independent causes, both confirmed against the live Gamma API:

1. **The field we read does not exist upstream.** `_extract_event_metadata` reads
   `raw.get("category")` from the `events[]` array nested inside a `/markets`
   response (`polymarket_sync.py:387`). That nested object carries neither
   `category` nor `tags` — `category` is `null` for every market. Polymarket's real
   taxonomy lives in `tags[]`.

2. **Existing events are never re-categorized.** `bind_market_to_upstream_event`
   does `event = existing or TableWrite.upsert_event(...)`. When the event is
   already known (matched by `POLYMARKET_EVENT_ID`), the upsert is skipped
   entirely, so no field — category included — is ever refreshed. The function's
   docstring claims it handles markets "whose upstream event was renamed/
   recategorized"; it does not.

### Measurements

Sampled 500 open, active, non-archived markets ordered by volume — the same
population `fetch_all_polymarket_markets` ingests:

| tags resolving to a canonical category | share |
|---|---|
| exactly one | 71% |
| more than one | 24% |
| none | 5% |

Collisions are overwhelmingly `Politics + World` (109 of 122). Those are
`Will China invade Taiwan`, `Putin out as President of Russia`, the Brazilian and
French presidential races — geopolitics, which Polymarket itself files under
**World**, reserving **Politics** for US domestic politics.

Of the 5% with no canonical tag, a 16-entry alias map recovers 21 of 23,
bringing total coverage to 99.6%. The stragglers are genuinely ambiguous
(`Jeffrey Epstein foul play confirmed by December 31, 2026?`).

All eight categories in the UI's `POLYMARKET_CATEGORY_ORDER` exist as Polymarket
tags, but two labels differ from what the UI expects: `pop-culture` is labelled
"Culture" upstream, and `technology` is lowercase.

## Approach

Three ways to obtain tags were evaluated against the live API:

| | extra requests per sync | verdict |
|---|---|---|
| **`&include_tag=true` on `/markets`** | **none** | tags arrive inline in the call the sync already makes. **Chosen.** |
| batch `GET /events?id=X&id=Y` | ~1 per 20 events | works, but adds a network stage for the same data |
| per-tag `GET /markets?tag_id=N` sweeps | 8 paginated sweeps | most expensive, and yields market→category rather than event→category |

Verified: without the parameter every market has `tags: null`; with it,
`tags: [{id, slug, label}, ...]`.

## Design

### 1. `agentpit/polymarket/category_resolver.py` — new pure module

No network, no database. A tag-slug list in, a category or `None` out.

```python
CATEGORY_PRIORITY = (
    "Sports", "Crypto", "Science", "Technology",
    "Pop Culture", "Business", "World", "Politics",
)

_CANONICAL_SLUGS = {
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

_ALIAS_SLUGS = {
    "geopolitics": "World", "middle-east": "World", "war": "World",
    "elections": "Politics",
    "finance": "Business", "economy": "Business", "economic-policy": "Business",
    "fed": "Business", "earnings": "Business", "oil": "Business",
    "inflation": "Business",
    "weather": "Science", "pandemics": "Science", "health": "Science",
    "space": "Science",
    "ai": "Technology",
}

def resolve_category(tag_slugs: Iterable[str]) -> str | None: ...
def category_rank(category: str | None) -> int: ...
```

`resolve_category` skips falsy entries (a malformed tag object yields `slug: None`),
lowercases and strips the rest, then runs two passes:
exact `_CANONICAL_SLUGS` first, `_ALIAS_SLUGS` second. **Within each pass the
winner is the one highest in `CATEGORY_PRIORITY`, not the one appearing first in
the input.** Gamma returns `tags[]` unordered, so first-match would assign
different categories to the same market on different sync passes.

An exact canonical tag always beats an alias, even a higher-priority one: the
alias map is a heuristic and must not override Polymarket's own labelling.

`category_rank` returns the index in `CATEGORY_PRIORITY`, or `len(CATEGORY_PRIORITY)`
for `None` and for any value not in the tuple (a free-form category written by
`POST /markets`). Lower rank means stricter.

Labels are normalised to what the UI expects, not to what Polymarket returns —
`pop-culture` → `Pop Culture`, `technology`/`tech` → `Technology`. Otherwise
`buildCategoryList` in `ui/src/pages/MarketsPage.tsx` fails to match them against
its canonical list and renders duplicate tabs ("Culture" alongside "Pop Culture").

The priority order encodes "narrower beats broader", with `Politics` last as the
catch-all. Against the measured collisions it yields: `Politics+World` → `World`
(109 markets), `Business+Technology` → `Technology` (6), `Politics+Pop Culture`
→ `Pop Culture` (3), `Crypto+Politics` → `Crypto` (1).

### 2. `polymarket_sync.py` — three edits

**a. `fetch_all_polymarket_markets`** — append `include_tag=true` to `base_query`.
No other change; markets now carry `tags`.

**b. `_extract_event_metadata`** — replace the dead `raw.get("category")` with

```python
"category": resolve_category(
    t.get("slug") for t in (pm_market.get("tags") or []) if isinstance(t, dict)
),
```

Tags are read from the **market**, not from the nested event object. The signature
`(pm_market: dict) -> dict | None` is unchanged, so callers and existing tests hold.
A missing or `null` `tags` yields `None`, which is the pre-change behaviour.

**c. `bind_market_to_upstream_event`** — categorize the already-known event.

```python
def _sync_event_category(db, event, category: str | None) -> None:
    """Raise an event's category when `category` is stricter than what's stored.

    Never clears: a market whose tags resolve to nothing (0.4% of the feed) must
    not undo a good categorization contributed by a sibling market.
    """
    if category is None:
        return
    if category_rank(category) >= category_rank(event.category):
        return
    TableWrite.update_event_category(db, event.event_id, category)
```

called on the `existing` branch. The create branch keeps passing
`category=meta["category"]` to `upsert_event`.

An event owns many markets, and sync order across them is not guaranteed. A
last-writer-wins update would let an event's category oscillate between passes.
Comparing ranks makes the outcome independent of processing order and converges
on the strictest category any member market resolves to.

The update goes through a new targeted `TableWrite.update_event_category`, **not**
through `upsert_event`. `upsert_event` matches on `SLUG`, but this event was found
by `POLYMARKET_EVENT_ID`; if upstream renamed the slug, a full upsert would insert
a duplicate row instead of updating the existing one.

### 3. Database and API

The schema does not change — `CATEGORY TEXT` already exists in
`table_create.py:187`. The only new write path is `TableWrite.update_event_category`.

One read-path edit: `WHERE CATEGORY = ?` becomes `WHERE CATEGORY = ? COLLATE NOCASE`
in `TableRead.list_events_with_markets`. We write canonical labels ourselves, so
this is insurance — today a case mismatch between the label the UI sends and the
label stored would silently return zero events rather than fail loudly.
`list_event_categories` already sorts `COLLATE NOCASE` and needs no change.

**No backfill script.** `_polymarket_sync_loop` in `agentpit/api/app.py` re-binds
every market on every pass, so once edit (c) lands, existing events acquire their
category on the next sync tick.

### 4. Tests

Written test-first, run with `.venv/bin/python -m pytest` — never source `.env`
into pytest, it defeats the `conftest` setdefaults.

`tests/polymarket/test_category_resolver.py` (new):
- exact canonical slug → its category
- priority beats input order: `["politics", "world"]` and `["world", "politics"]`
  both → `World`
- an exact canonical tag beats a higher-priority alias
- alias pass only fires when no canonical tag matched
- unknown slugs, an empty iterable, and an iterable of `None`s → `None`
- slugs are matched case-insensitively and whitespace-trimmed
- `category_rank` orders `CATEGORY_PRIORITY` and sinks unknown/`None` to last

`tests/polymarket/test_polymarket_event_capture.py` (existing, extended):
- a market carrying `tags` creates its event with the resolved category
- an existing event with a broader category is upgraded to the stricter one
- an existing event with a stricter category is **not** downgraded
- a market resolving to `None` leaves a stored category intact
- a market with no `tags` key behaves as before

`tests/db/test_events_dal.py` (existing, extended):
- `update_event_category` writes and is idempotent
- the category filter matches across case via `COLLATE NOCASE`

The category tests already on the branch (`tests/api/test_events.py`,
`tests/services/test_event_service.py`, `tests/db/test_events_dal.py`) must stay green.

## Known limitation

If an event exists under a given `SLUG` but has no `POLYMARKET_EVENT_ID`, the
`existing` lookup misses and the create branch runs `upsert_event`, whose UPDATE
overwrites `CATEGORY` with `meta["category"]` — possibly `None`. This affects every
column the upsert touches, predates this work, and is reachable only for the 0.4%
of markets that resolve to nothing. Left as is rather than changing `upsert_event`'s
semantics, which the seeder also depends on.

## Non-goals

- **Subcategory chips.** `CATEGORY_SUBCATEGORIES` in `MarketsPage.tsx` stays
  client-side keyword matching. Making those real requires storing raw tags, which
  the "one category per event" decision rules out.
- **An `event_tags` table.** Not needed for a single-category filter.
- **Validating the free-form `category` on `POST /markets`** against the eight
  canonical values.
- **`ui/src/components/TopNav.tsx`.** This branch reverts `useTheme` back to
  `getResolvedTheme`/`setTheme`, which appears to undo commit `15a6bf4`. Unrelated
  to categories; flagged because it will surface at merge time.
