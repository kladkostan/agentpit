# Sort homepage events by upstream 24h volume — design spec

**Date:** 2026-06-11
**Status:** Approved (pending implementation plan)
**Area:** `agentpit/db/`, `agentpit/polymarket/`, `agentpit/datastructures/`
**Scope:** Backend-only (no frontend changes)

## 1. Overview

The homepage lists events ordered by `EVENT_ID DESC` (creation order), paginated 20
per page via infinite scroll. Recurring high-frequency markets (e.g. *BTC Up or Down
5m*) bind to an event created early in the startup sequence (`event_id 6`), so among
~41 events it ranks **36th** — on the second scroll page, effectively invisible.

This feature sorts the homepage by **upstream Polymarket 24h volume**, so the events
people actually trade (including the recurring series) surface at the top, mirroring
Polymarket's own ranking.

### Why upstream volume (not local/aggregated)

agentpit currently stores **no** volume data — neither `events` nor `markets` has a
volume column, and the Gamma serializer hardcodes `volume="0"`. Three sources were
considered:

- **Local traded 24h volume** (sum of agentpit on-chain trades) — "real" activity, but
  BTC and nearly every event would rank ~0 until traded, so it would *not* surface the
  target market. Rejected.
- **Sum of member-market upstream volume** — for BTC the 5m windows are ~$200 each, so
  the event stays at the bottom. Rejected.
- **Upstream Polymarket `volume24hr`** (chosen) — capture Polymarket's own 24h-volume
  number at sync time and store it on the event. Mirrors Polymarket's ranking, so BTC
  Up or Down 5m surfaces near the top. The number is a snapshot, refreshed each sync.

### Verified against live Gamma (2026-06-11)

- A **trending market's** upstream `events[0]` object carries `volume24hr` (e.g.
  `7967.77`) — and for a multi-market event this is already the **event aggregate**, so
  no client-side summing is needed.
- The **window event** of a recurring series has `volume24hr = None`, but its
  `series[0].volume24hr` is large (e.g. `14_646_954`). So for recurring series we must
  capture the **series** value; the window event's own is null.
- This makes capture uniform: every agentpit event stores its upstream
  **event-or-series** `volume24hr`.

## 2. Goals / Non-goals

### Goals
- Persist an upstream 24h-volume figure on each event, refreshed every sync pass.
- Capture it uniformly across both sync paths: trending (`events[0].volume24hr`) and
  pinned-series (`series[0].volume24hr`).
- Order the homepage event listing by that volume, descending.
- Zero frontend changes — the homepage already renders the API order.

### Non-goals
- **No local/traded-volume computation.** Out of scope; upstream snapshot only.
- **No per-market volume display or sorting.** Only event-level ordering changes.
- **No frontend card redesign.** The `volume` value is exposed through the existing
  `GammaEvent.volume` field for possible later display, but no `ui/` change ships here.
- **No backfill job.** Volume is populated lazily as each event is re-synced (the next
  trending/pin pass refreshes every actively-synced event). Events never re-synced
  (stale/closed) keep `NULL` volume and sort last — acceptable.

## 3. Data model

Add a nullable column to the `events` table:

```sql
VOLUME_24HR DOUBLE PRECISION
```

- Created idempotently in `TableCreate` via
  `ALTER TABLE events ADD COLUMN IF NOT EXISTS VOLUME_24HR DOUBLE PRECISION`
  (mirroring the existing users-table migration pattern at `table_create.py:119`), so
  the running production DB upgrades on the next startup — **no `db_reset` required**.
- Add a supporting index:
  `CREATE INDEX IF NOT EXISTS idx_events_volume_24hr ON events(VOLUME_24HR)`.
- Nullable (not `DEFAULT 0`) so "never had upstream volume" (orphan singletons,
  pre-existing rows) is distinguishable and sorts last via `NULLS LAST`.

Add to the `Event` datastructure (`agentpit/datastructures/event.py`):
`volume_24hr: float | None = None`, and include `VOLUME_24HR` in `TableRead._EVENT_COLS`
and `_row_to_event`.

## 4. Capture during sync

The capture seam is the existing event-binding path; both sync paths converge on
`bind_market_to_upstream_event` → `upsert_event`.

### 4a. Trending path
`_extract_event_metadata(pm_market)` (in `polymarket_sync.py`) already pulls the event
fields from `pm_market["events"][0]`. Add one field:
```python
"volume_24hr": _as_float(raw.get("volume24hr")) if raw.get("volume24hr") is not None else None,
```
(`_as_float` already exists in the module.)

### 4b. Pinned-series path
`_event_entry(src)` (in `pinned.py`) builds the events-array entry consumed by
`_extract_event_metadata`. Add `"volume24hr": src.get("volume24hr")` to the dict it
returns, so:
- For the series entry (`series_event_metadata` → `_event_entry(event["series"][0])`),
  the large series `volume24hr` flows through.
- For the window-event fallback (`_event_entry(event)`), the window's own `volume24hr`
  (null) flows through — correctly leaving the event at `NULL` until the series is
  available.

Because `_extract_event_metadata` reads `volume24hr` from its input entry, the injected
series entry's value is picked up with no further change in the pinned path.

### 4c. Write + refresh
A dedicated, guarded write keeps volume current on **every** sync pass for both new and
existing events, without touching the event-id-match dedup:

`TableWrite.update_event_volume(db, event_id, volume_24hr)`:
- **No-op when `volume_24hr is None`** — so a window-only fallback pass (no series, null
  volume) never clobbers a previously-captured good value.
- Otherwise `UPDATE events SET VOLUME_24HR = %s WHERE EVENT_ID = %s`.

`bind_market_to_upstream_event` resolves the event as today
(`existing = get_by_polymarket_event_id(...)` then `event = existing or upsert_event(...)`),
then calls `update_event_volume(db, event.event_id, meta["volume_24hr"])` unconditionally.
This means:
- **New event:** `upsert_event` inserts the row (volume `NULL`), then
  `update_event_volume` populates it (when non-null).
- **Existing event** (matched by `polymarket_event_id` *or* slug): refreshed each pass.

`upsert_event` itself is **unchanged** — no new column param — keeping a single, uniform
volume-write seam (`update_event_volume`) rather than splitting the logic across two
write paths.

## 5. Sort

`TableRead.list_events_with_markets` changes its event query ordering from:
```sql
ORDER BY EVENT_ID DESC
```
to:
```sql
ORDER BY VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC
```
- Highest upstream 24h volume first.
- `NULLS LAST`: events with no captured volume (orphan singletons, not-yet-refreshed
  rows) fall to the bottom.
- `EVENT_ID DESC` tiebreak: stable, newest-first within equal/!null volume.

Pagination math is unchanged (still `LIMIT/OFFSET`); only the order differs.

## 6. Serialization (no frontend change)

`to_gamma_event(event, markets)` sets `volume=str(event.volume_24hr or 0)` (it currently
omits volume, defaulting to the `GammaEvent` field default). The frontend type already
declares `volume: string`; the homepage renders events in the API-returned order, so the
new sort takes effect with **zero `ui/` changes**. Exposing the number also lets a future
iteration display it without backend work.

## 7. Lifecycle / refresh

- Trending sync (hourly) refreshes volume for every top-N event it re-syncs.
- Pin-sync (every 5 min) refreshes the series event's volume each pass.
- An event that stops being synced keeps its last-known (or `NULL`) volume and drifts
  down the list — acceptable; it's no longer active.

## 8. Failure modes / edge cases

- **Upstream omits `volume24hr`:** stored as `NULL` → sorts last. No error.
- **Non-numeric volume:** `_as_float` coerces; unparseable → `0.0`/`None` per the helper.
- **Orphan/singleton events** (locally-authored, no upstream): `NULL` volume → sort last.
- **Pre-existing event rows** (before this feature): `NULL` until next re-sync, then
  populated. They sort last until refreshed — expected.
- **Two member markets of one event** both carry the same event-level `volume24hr`
  (Gamma returns the aggregate per market), so repeated upserts rewrite the same value —
  idempotent.

## 9. Testing

- **DB (ordering):** insert events with volumes `{100, NULL, 5000}` →
  `list_events_with_markets` returns `5000, 100, NULL` order; NULL last.
- **Migration:** `create_all_tables` on a DB lacking the column adds it (idempotent on
  re-run); `_row_to_event` reads it.
- **Capture (trending):** `_extract_event_metadata` returns `volume_24hr` from
  `events[0].volume24hr`; `None` when absent.
- **Capture (pinned):** `_event_entry`/`series_event_metadata` carries
  `series[0].volume24hr`; a window-only event (no series) yields `None`.
- **Bind refresh:** binding a market whose upstream event volume changed updates the
  stored `VOLUME_24HR` on a subsequent pass (not just on first insert).
- **Serializer:** `to_gamma_event` emits `volume` as the stringified value (`"0"` when
  `NULL`).
- **Integration (optional, DB-level):** the BTC series event ends up with the series
  volume (large) while its window markets are tiny — proving the series value wins.

## 10. Files touched

- `agentpit/db/table_create.py` — `ALTER TABLE events ADD COLUMN IF NOT EXISTS
  VOLUME_24HR …` + index.
- `agentpit/db/table_read.py` — `_EVENT_COLS`, `_row_to_event`, and the
  `list_events_with_markets` ORDER BY.
- `agentpit/db/table_write.py` — new `update_event_volume(db, event_id, volume_24hr)`
  helper (no-op on `None`). `upsert_event` unchanged.
- `agentpit/datastructures/event.py` — `volume_24hr: float | None`.
- `agentpit/polymarket/polymarket_sync.py` — `_extract_event_metadata` extracts
  `volume_24hr`; `bind_market_to_upstream_event` passes it through.
- `agentpit/polymarket/pinned.py` — `_event_entry` carries `volume24hr`.
- `agentpit/polymarket/gamma.py` — `to_gamma_event` emits `volume`.
- `tests/` — DB ordering, migration, capture (both paths), bind-refresh, serializer.

## 11. Deferred follow-ups (out of scope)

- Displaying the 24h-volume figure on event cards in `ui/`.
- A periodic volume-only refresh decoupled from market discovery (today volume refreshes
  only when an event is re-synced).
- Local/traded-volume metrics as a separate, additional signal.
