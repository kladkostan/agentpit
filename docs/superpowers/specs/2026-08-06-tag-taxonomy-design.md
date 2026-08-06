# Tag-Driven Category Navigation — Design

**Status:** approved for planning
**Date:** 2026-08-06
**Branch:** `mvp`

## Goal

Replace the lossy one-category-per-event taxonomy with the real Polymarket tag
graph, so the markets sidebar offers roughly sixteen categories and up to twenty
subcategories each instead of eight categories and three hardcoded keyword
filters.

## Non-goals

- **No layout change.** [`MarketsPage.tsx`](../../../ui/src/pages/MarketsPage.tsx)
  already renders the Polymarket shape: a sticky `220px` sidebar, a vertical
  category list, a chevron per category, an indented subcategory list beneath
  it, plus a horizontal scroll row on mobile. Every component, class name,
  icon and expand/collapse behaviour stays exactly as it is. Only the data
  filling them changes.
- **No event counts in the UI.** The API returns them (ordering needs them),
  but rendering a count next to a label is a visual change and stays out.
- **No dynamic promotion of trending tags into the top level.** Polymarket
  surfaces news-driven tags like `iran` in its own nav; ours stays a curated
  ordered list. Revisit only if the curated list proves stale in practice.
- **No removal of the `CATEGORY` column or `resolve_category`.** The
  local-market create path still writes a free-form category, and
  `EventDetailPage` renders it as a badge. Navigation simply stops reading it.

## Evidence

Measured on 2026-08-06 against production and the live Gamma API. All 1714
production events resolved upstream, none unresolved.

| Fact | Value |
| --- | --- |
| Events in production | 1714 |
| Events created locally (no `POLYMARKET_EVENT_ID`) | 0 |
| Distinct tag slugs across those events | 759 |
| Mean tags per event | 4.6 |
| Events under `Sports` today | 895 (52% of the catalogue) |
| Filters in the sidebar today | 8 categories + ~26 subcategories |

Two structural findings drive the design:

1. **Gamma's tag objects already carry display labels.** `pop-culture` has
   label `Culture`; `global-elections` has `Global Elections`. The
   `_CANONICAL_SLUGS` normalisation table in `category_resolver.py` exists only
   because we discarded those labels.
2. **Polymarket's own navigation is tag slugs.** Every entry in its visible nav
   row maps 1:1 to a tag slug, and its per-category sidebar is co-occurring
   tags ordered by event count.

## Architecture

Tags are stored per market, because that is where Gamma puts them and because a
per-market replace on every sync pass is self-healing: a tag removed upstream
disappears locally. An event-level union can only ever grow. An event's tag set
is the union over its markets, computed by join at read time.

```
Gamma /markets?include_tag=true
        │  tags[] = [{slug, label}, …]
        ▼
bind_market_to_upstream_event()          ← already runs on every sync pass
        │  replace_market_tags(market_id, tags)
        ▼
    market_tags                          ← new table
        │  JOIN markets ON MARKET_ID → EVENT_ID
        ▼
GET /tags            → curated top-level list, present-only, count ≥ 10
GET /tags?parent=…   → co-occurring facets, ordered by count, capped at 20
GET /events?tag=&subtag=  → server-side filtering
        ▼
   MarketsPage sidebar (unchanged markup)
```

## Data model

```sql
CREATE TABLE IF NOT EXISTS market_tags (
    MARKET_ID BIGINT NOT NULL,
    SLUG      TEXT   NOT NULL,
    LABEL     TEXT   NOT NULL,
    PRIMARY KEY (MARKET_ID, SLUG)
);
CREATE INDEX IF NOT EXISTS idx_market_tags_slug ON market_tags(SLUG);
```

Created in `TableCreate.create_market_tags_table`, called from the same
startup path as every other table. Idempotent, so the running database
upgrades on boot with no reset.

No foreign key: the existing schema uses plain columns plus indexes
throughout (`markets.EVENT_ID` has no FK either), and this table follows the
established convention rather than introducing a new one.

`SLUG` is stored lowercase and stripped. Gamma is inconsistent — the observed
crypto facet list contained a literal `1H` alongside lowercase siblings — and
an unnormalised slug would split one facet into two.

## Sync write path

`TableWrite.replace_market_tags(db, *, market_id, tags)` deletes that market's
rows and inserts the supplied set in one transaction.

It is called from
[`bind_market_to_upstream_event()`](../../../agentpit/polymarket/polymarket_sync.py),
the same function where `resolve_category` currently collapses the list. That
function is invoked on every sync pass for every upstream market, via
`bind_existing_market_to_upstream_event` for already-known markets and directly
for newly created ones.

**Guard:** the replace runs only when the upstream payload actually carried a
`tags` list. When `tags` is `null` or absent — which is what a request without
`include_tag=true` returns — the write is skipped entirely, so a code path that
forgets the parameter cannot wipe good data. This mirrors the COALESCE
discipline the rest of the sync module already follows.

Malformed entries are skipped individually: an element that is not a dict, or
whose `slug` is missing or not a string, is dropped rather than raising. A
raise here would permanently skip that market on every future pass.

## Taxonomy constants

New module `agentpit/polymarket/tag_taxonomy.py`, beside `category_resolver.py`.

**`NAV_SLUGS`** — the curated top-level order. Rendered only when a slug is
actually present in the database with at least `MIN_NAV_EVENTS` events, which
preserves the existing rule that a visible tab must never yield an empty grid.

```
politics, sports, crypto, elections, geopolitics, tennis, esports, soccer,
weather, tech, pop-culture, finance, economy, world, ai, business, science
```

**`BLOCKED_SLUGS`** — Polymarket's operational tags, which describe how a
market is scheduled or settled rather than what it is about:

```
hide-from-new, recurring, daily, weekly, monthly, yearly, hourly, 4h, 1h,
today, extended, new, trending, all, up-or-down, hit-price, multi-strikes,
price-milestone, neg-risk, main-election, earn-4
```

`games` is deliberately absent: it is uninformative under `sports` but the
coverage rule below removes it there on the data rather than on a hunch, and
under a parent where it is genuinely selective it should survive.

Plus a prefix rule: any slug beginning `deprec-` is blocked.

Gamma's own `forceShow` / `forceHide` fields cannot substitute for this list —
`politics` is published with `forceHide: true`, and the fields are absent from
the embedded tag objects anyway, reachable only through a separate request per
tag.

**Thresholds:**

- `MIN_NAV_EVENTS = 10` — below this a top-level entry is hidden. On today's
  data this hides `science` (9 events).
- `MAX_FACET_COVERAGE = 0.9` — a facet matching more than 90% of its parent
  says nothing and is dropped. This removes `games` from `sports` (832 of 895).
- `MAX_FACETS = 20` — cap on the subcategory list length.

## Read path

Two new methods on `TableRead`.

**`list_tag_nav(db, *, slugs, min_events)`** returns
`list[tuple[slug, label, event_count]]` for the requested slugs that clear the
threshold. Ordering is applied by the caller against `NAV_SLUGS`, so the
curated order survives.

```sql
SELECT mt.SLUG AS SLUG, MIN(mt.LABEL) AS LABEL,
       COUNT(DISTINCT m.EVENT_ID) AS CNT
FROM market_tags mt
JOIN markets m ON m.MARKET_ID = mt.MARKET_ID
WHERE m.EVENT_ID IS NOT NULL AND mt.SLUG = ANY(%s)
GROUP BY mt.SLUG
HAVING COUNT(DISTINCT m.EVENT_ID) >= %s
```

**`list_tag_facets(db, *, parent_slug, blocked, limit, max_coverage)`** returns
the same triple shape for tags co-occurring with `parent_slug`. It counts the
parent's own events from the CTE and applies both the coverage ceiling and the
cap itself, so the caller receives a finished list.

```sql
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
  AND mt.SLUG NOT LIKE 'deprec-%%'
GROUP BY mt.SLUG
ORDER BY CNT DESC, mt.SLUG ASC
```

`MIN(LABEL)` rather than an arbitrary pick: the same slug could carry differing
labels across markets after an upstream rename, and the result must be
deterministic across calls.

**`list_events_with_markets`** gains `tag: str | None` and
`subtags: list[str] | None`, alongside the existing `category`. The filters
compose as AND between them and OR within `subtags`. Each is a predicate fed
into the method's existing `where` builder — the first present filter opens the
`WHERE`, the rest join with `AND`:

```sql
-- tag: one predicate
EXISTS (SELECT 1 FROM markets m
        JOIN market_tags mt ON mt.MARKET_ID = m.MARKET_ID
        WHERE m.EVENT_ID = events.EVENT_ID AND mt.SLUG = %s)

-- subtags: one predicate, OR within via ANY()
EXISTS (SELECT 1 FROM markets m
        JOIN market_tags mt ON mt.MARKET_ID = m.MARKET_ID
        WHERE m.EVENT_ID = events.EVENT_ID AND mt.SLUG = ANY(%s))
```

Blank and whitespace-only values count as absent, matching how `category` is
already normalised. `total` reflects the same filter. The existing
`ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC` is untouched, so the
ordering guarantee the home page depends on still holds.

The parent tag stays in the query even when subtags are selected. Facets are
derived within a parent, but a tag like `trump` also occurs outside `politics`,
and dropping the parent would let a Politics → Trump selection surface a
non-Politics event.

## API

New router `agentpit/api/routes/tags.py`.

```
GET /tags → {"tags": [
    {"slug": "politics", "label": "Politics", "count": 304,
     "facets": [{"slug": "elections", "label": "Elections", "count": 161}, …]},
    …
]}
```

One endpoint, facets nested, not a separate `?parent=` call. The sidebar
renders a chevron for every category at once and must know which ones have
subcategories before any of them is expanded; a per-parent endpoint would mean
sixteen requests on mount or a chevron that appears only after expansion. The
whole payload is roughly sixteen entries of at most twenty facets each.

The service builds it with one `list_tag_nav` call plus one `list_tag_facets`
call per surviving nav slug — about seventeen indexed queries, run at most once
per cache TTL. A single self-joining query would do it in one round trip, but
the loop is the version an implementer can read and unit-test one piece at a
time, and the cache makes the difference invisible.

`GET /events` gains `tag` and repeatable `subtag` query parameters. `category`
is retained unchanged for backwards compatibility.

`/tags` takes no parameters, so its cache is a single slot holding
`(timestamp, response)` with a 30-second TTL — the data only changes when a
sync runs, an hour apart.

`_events_cache`'s key must be extended to include `tag` and the `subtags`
tuple, or a filtered page would be served to an unfiltered request for up to
one TTL. Both caches must be cleared in `tests/conftest.py` beside the existing
`_events_route._events_cache.clear()`, or one test's page leaks into the next.

A service method `list_tags()` goes on the existing `EventService` — tags are
facets over events, and the class is small enough that one method does not
warrant a new dependency-injected service.

## UI

`ui/src/api/tags.ts` (new) exposes `useTags()`, one query against `/tags`.

Deleted from `MarketsPage.tsx`: `CATEGORY_SUBCATEGORIES`, `SubcategoryOption`,
`getSubcategories`, `eventMatchesKeywords`, and the `POLYMARKET_CATEGORY_ORDER`
/ `buildCategoryList` pair — ordering now arrives from the server already
applied.

Selection state moves from label strings to slugs: `selectedCategory` holds a
tag slug, `selectedSubcategories` holds facet slugs scoped by parent. Because
subcategory filtering is now a server query, `useEventsInfinite` takes the tag
and subtag slugs as part of its key, and the eager "fetch every remaining page"
effect narrows to the search box only — search remains client-side, so its
branch of `hasClientSideFilter` stays.

`CATEGORY_ICONS` is rekeyed by slug and extended to cover the curated list.
`getCategoryIcon` keeps its `Tag` fallback, so a slug with no icon still
renders.

The mobile row and the desktop sidebar both consume the same fetched lists;
neither branch's markup changes.

## Error handling

- `/tags` failing leaves the sidebar with only "All". The events grid is
  independent and keeps working.
- A tag present in the UI but absent from the database after a sync returns an
  empty grid, which the existing "no results" state already covers.
- The sync's tag write is best-effort per market: a malformed `tags` entry is
  skipped, never raised, so one bad market cannot stall a pass.

## Testing

**Backend** (`.venv/bin/python -m pytest tests -q --ignore=tests/onchain`,
never with `.env` sourced):

- `create_market_tags_table` is idempotent across two calls.
- `replace_market_tags` replaces rather than accumulates; a slug removed
  upstream disappears.
- The sync skips the write when `tags` is `null` or the key is absent, leaving
  existing rows intact.
- Slugs are lowercased and stripped on write; `1H` and `1h` collapse to one row.
- A malformed tag entry is skipped without raising.
- `list_tag_nav` honours the threshold and returns curated order.
- `list_tag_facets` excludes the parent, blocked slugs, `deprec-` prefixed
  slugs, and facets above the coverage ceiling; caps at 20.
- `list_events_with_markets` filters by `tag`, by `tag` + `subtags` (AND across,
  OR within), and treats blank values as absent.
- `/tags` cache is keyed by `parent`; `/events` cache is keyed by tag and
  subtags.

**UI** (`npx vitest run && npm run typecheck && npm run lint && npm run build`
from `ui/`, node environment, no `@testing-library/react`):

- `listTags` requests `/tags` and returns the nested shape unchanged.
- The events query serialises `tag` and repeated `subtag` parameters, and omits
  them when blank.
- No hardcoded subcategory map survives in the bundle.

`ui/` runs vitest in the **node** environment with no `@testing-library/react`
installed, so there is no way to render `MarketsPage` in a test. Its correctness
rests on the pure functions it calls (which are tested), plus `npm run
typecheck`, `npm run lint` and `npm run build`. Any new test must be a
pure-logic `.ts` test.

## Rollout

The schema is created on startup and the Polymarket sync runs immediately on
boot before its first sleep, so deploying the API populates `market_tags`
within one sync pass — not the hour-long interval. During that pass `/tags`
returns fewer entries; the present-only rule means it never returns a wrong
one, so the sidebar is briefly short rather than broken. No separate backfill
script is required.

Backend and UI ship together.

## Known behaviour and follow-ups

- **Science and Business shrink.** They currently hold 162 and 85 events only
  because the alias map in `category_resolver.py` folds `weather`, `fed`,
  `oil` and `earnings` into them. On real tags `science` falls to 9 (hidden by
  the threshold) and `business` to 19, while `weather` becomes its own entry
  with 157. This is more truthful, but the numbers move visibly.
- **A locally created market has no tags** and therefore appears only under
  "All", not under any category tab. Production has zero such events today, so
  this affects nothing now; if local markets return, seeding `market_tags` from
  their `CATEGORY` at creation is the fix.
- **Pinned-series markets arrive without tags.** `agentpit/polymarket/pinned.py`
  fetches `GET /events?slug=…` from Gamma with no tag parameter, so the markets
  it hands to the shared creation path already resolve to `category=None`
  today, and will likewise carry no tags. This is a pre-existing gap, not one
  this change introduces, and it is out of scope here — the fix is to request
  tags on that endpoint too, tracked separately.
- Event counts beside labels, and dynamic promotion of trending tags into the
  top level, are both deliberately deferred (see Non-goals).
