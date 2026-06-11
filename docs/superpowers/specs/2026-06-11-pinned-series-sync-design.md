# Pinned-series sync — design spec

**Date:** 2026-06-11
**Status:** Approved (pending implementation plan)
**Area:** `agentpit/polymarket/`, `agentpit/config.py`, `agentpit/api/app.py`
**Scope:** Backend-only (no frontend changes in v1)

## 1. Overview

Top-N-by-24h-volume sync (the trending-sync feature) structurally **cannot** capture
high-frequency recurring markets such as *BTC Up or Down 5m*. Each individual
5-minute window has tiny volume **while it is tradeable** (~$200, well below the
top-300 cutoff of ~$863) and only accumulates high volume **after it closes** (when
it is no longer tradeable). So volume ranking never surfaces the live window.

This feature **pins recurring series explicitly** and force-syncs the **current live
window** of each, regardless of volume rank, on a **phase-aligned** schedule. All
windows of a series are grouped under **one agentpit event** (one homepage card),
reusing the existing event-grouping. The window's lifecycle then closes through the
already-built resolution-mirror + auto-redeem loop.

### Findings that motivate the design (verified against live Gamma)

- The recurring markets form a family `{asset}-updown-{interval}-{grid_ts}`: at least
  **15 series** (assets `btc, eth, sol, xrp, doge` × intervals `5m, 15m, 4h`).
- Polymarket has a first-class **series** concept (`GET /series`) with an
  **aggregate** `volume24hr` — `BTC Up or Down 5m` (series id `10684`,
  `recurrence: 5m`) ranks ~#3 by volume. The UI sorts the **series/events** feed, not
  individual markets, which is why the card looks high-volume while a single window is
  tiny.
- Each window is its own **event** with slug `btc-updown-5m-{grid_ts}` (note: the
  **event** slug `btc-updown-5m` ≠ the **series** slug `btc-up-or-down-5m`), and the
  event carries a `series` field (id/slug/title/recurrence).
- Windows are **pre-created ~24h ahead** (current + many future windows exist
  simultaneously, all with `acceptingOrders: true`), so fetching the current window
  always succeeds — no "wait for the window to appear".
- `current_window_slug = f"{base}-{now - (now % interval)}"` resolves exactly to the
  window whose `[start, end)` contains `now` (verified: at 10:28, grid → 10:25 window).
- Each window's question is **unique** (it embeds the time range), so windows do **not**
  collide on the locally-derived `condition_id = keccak(question)`.

## 2. Goals / Non-goals

### Goals
- Force-sync the **current live window** of each configured series every cycle,
  regardless of volume rank.
- A **phase-aligned scheduler**: wake shortly after each window boundary so the
  now-live window is synced promptly (~10s of latency, not up to a full poll interval).
- Group all windows of a series under **one** agentpit event → one homepage card,
  reusing existing event grouping (no new series table, no frontend change).
- Close each window's lifecycle through the existing resolution-mirror + auto-redeem
  loop (window resolves upstream → `reportPayouts` on-chain → `RESOLVED` → auto-redeem).

### Non-goals (v1)
- **Pre-syncing future windows (lookahead).** Windows pre-exist, so we *could* prepare
  the next window on-chain before it goes live; deferred because a pre-synced future
  window would become `ACTIVE`+synced and the liquidity mirror would start mirroring it
  before it is the live window. (Cost: ~10s of prep latency at each window open.)
- **Pruning accumulated resolved windows.** Each window is a new market (288/day per
  5m series); resolved windows accumulate under the series event. DB-growth pruning is a
  follow-up.
- **Frontend polish.** No `ui/` changes. The series renders on existing components
  (functional, not a Polymarket-style window switcher).
- **Auto-discovery of series by volume.** A config allow-list is used instead.

## 3. Configuration

| env | type / default | meaning |
|---|---|---|
| `PINNED_SERIES` | str, `"btc-updown-5m:300"` | Comma-separated `event_slug_base:interval_seconds` entries (e.g. `btc-updown-5m:300,eth-updown-5m:300`). Parsed to `list[(base, interval)]`. |
| `PIN_SYNC_ENABLED` | bool, default = `SYNC` | Gate for the pin-sync loop (mirrors how `RESOLUTION_MIRROR_ENABLED` defaults to `SYNC`). |
| `PIN_SYNC_OFFSET_SECONDS` | int, `10` | Seconds after a window boundary to wake (safety margin; window already exists, so this is slack, not a wait). |

The poll interval is **not** a separate knob — the scheduler aligns to the **smallest
interval among the configured series** (e.g. 300s).

## 4. New module: `agentpit/polymarket/pinned.py`

Pure, focused functions (each independently testable):

- `parse_pinned_series(raw: str) -> list[tuple[str, int]]`
  Parse `"base:interval,base:interval"` → `[(base, interval), ...]`; skip malformed
  entries with a warning.

- `current_window_slug(base: str, interval: int, now: int) -> str`
  `f"{base}-{now - (now % interval)}"` — exact slug of the window live at `now`.

- `fetch_event_by_slug(slug: str) -> dict | None`
  `get(f"{POLYMARKET_GAMMA_URL}/events?slug={slug}")` → first element, or `None`.

- `series_event_metadata(event: dict) -> dict | None`
  From `event["series"][0]` build an upstream-event dict shaped like the entries
  `_extract_event_metadata` consumes (`id`, `slug`, `title`, `image`/`icon`,
  `startDate`/`endDate`, `category`). Using the **series** id/slug/title (not the
  per-window event) is what groups all windows under one agentpit event. Returns `None`
  if the event has no `series`.

- `sync_pinned_series(conn, admin, pinned, now) -> list[Market]`
  For each `(base, interval)`:
  1. `slug = current_window_slug(base, interval, now)`
  2. `event = fetch_event_by_slug(slug)`; if `None` or no `event["markets"]`, skip.
  3. Inject the series grouping: set each window-market's `events = [series_event]`
     (from `series_event_metadata(event)`), so the existing
     `bind_market_to_upstream_event` attaches the window to the **series-level** event
     (one card). If the series metadata is absent, fall back to binding by the window
     event (per-window card) rather than failing.
  4. `created += create_polymarket_markets_if_needed(conn, event["markets"], admin)`
     — reuses the whole creation path: on-chain `prepareCondition`+`registerToken`,
     dedup by `polymarket_id`, event binding.
  Per-series `try/except` so one bad series never blocks the others.

- `next_wake_delay(now: int, align_interval: int, offset: int) -> float`
  `((now // align_interval + 1) * align_interval + offset) - now` — seconds until the
  next boundary + offset. Recomputed from the current time each iteration, so a slow
  cycle that overruns a boundary simply skips missed boundaries (no drift accumulation).

## 5. Scheduler (lifespan loop in `agentpit/api/app.py`)

- `_run_pin_sync(db, admin, settings) -> int`
  `now = int(time.time())`; `with db.write() as conn: created = sync_pinned_series(conn, admin, settings.pinned_series, now)`; return `len(created)`.

- `_pin_sync_loop(db, admin, settings)` — phase-aligned:
  ```
  while True:
      try:
          count = await asyncio.to_thread(_run_pin_sync, db, admin, settings)
          log "pin-sync: synced N current windows"
      except CancelledError: raise
      except Exception: log.exception(...)
      align = min(interval for _, interval in settings.pinned_series)  # e.g. 300
      await asyncio.sleep(next_wake_delay(int(time.time()), align, settings.pin_sync_offset_seconds))
  ```
  (If `pinned_series` is empty, the loop is not started.)

- Lifespan wiring: start `pin_task` when `settings.pin_sync_enabled` (else a "disabled"
  log), declared before `try: yield`, and added to the shutdown cancellation tuple
  alongside `sync_task` / `snapshot_task` / `resolution_task` / `mirror_tasks`.

Multiple series with different intervals all sync each `align`-boundary; longer-interval
windows are idempotently skipped between their own boundaries (already synced).

## 6. Series-event grouping (display, no frontend change)

The window-market fetched via `/events?slug=` is nested under its event and has no
`events` array, so the generic binding would no-op. We inject `events = [series_event]`
(built from the event's `series[0]`) so `bind_market_to_upstream_event` upserts **one**
agentpit event per series (matched by the series id as `polymarket_event_id`) and
attaches every window to it.

Result on the existing UI (no `ui/` changes):
- **Homepage:** one card per series (e.g. "BTC Up or Down 5m"), not a flood of
  per-window cards.
- **Detail / under the event:** the current window is the `ACTIVE` market; resolved
  past windows remain as `RESOLVED` markets under the same series event (history). The
  active market **rotates** every interval. Rendering is functional but not a polished
  window switcher (deferred).

## 7. Lifecycle (reuses already-built loops)

1. Pin-sync creates the current window → on-chain prepared → `ACTIVE`+synced.
2. Liquidity mirror (if enabled) provides liquidity → the window is tradeable; the agent
   trades it via the API.
3. Window closes upstream → the resolution-mirror loop (5 min) detects `closed` + winner
   → `reportPayouts` on-chain → flips the row to `RESOLVED`.
4. Auto-redeem (same loop) redeems holders.
5. The next window is synced on the next pin cycle as the new `ACTIVE` market under the
   same series event.

## 8. Failure modes / edge cases

- **Window slug not found** (off-grid / not yet created): `fetch_event_by_slug` → `None`
  → skip that series this cycle; retry next.
- **Per-series isolation:** one series raising never blocks the others.
- **Cycle overruns a boundary:** `next_wake_delay` recomputes from the current time and
  skips missed boundaries — no drift.
- **No `series` on the event:** fall back to per-window event binding (still synced &
  tradeable; just a per-window card) — log it.
- **DB growth:** resolved windows accumulate under the series event (288/day per 5m
  series). Pruning is a documented follow-up; the homepage stays clean (one card).
- **Non-binary window** (shouldn't happen for up/down): `prepare_market_on_chain` raises
  and the existing `create_polymarket_markets_if_needed` try/except drops it.

## 9. Testing

- **Unit (pure):**
  - `parse_pinned_series` — valid/empty/malformed input.
  - `current_window_slug` — grid math (e.g. base `btc-updown-5m`, interval 300,
    `now=1781188099` → `btc-updown-5m-1781187900`).
  - `next_wake_delay` — boundary + offset; overrun skips missed boundaries.
  - `sync_pinned_series` with a fake `fetch_event_by_slug` returning a fake event:
    asserts `create_polymarket_markets_if_needed` is called with the window market and
    that the injected `events` carries the **series** metadata (grouping).
- **DB-level:** two different window-markets of the same series bind to the **same**
  `event_id` (one card); windows of different series bind to different events.
- **On-chain integration:** pin a fake series event → `sync_pinned_series` → the window
  market is created, on-chain prepared, and attached to the series event.
- **Lifespan wiring:** `_run_pin_sync` calls `sync_pinned_series` inside a `db.write()`;
  loop gated on `pin_sync_enabled` (monkeypatched test, mirroring the resolution-loop
  wiring test).

## 10. Files touched

- `agentpit/polymarket/pinned.py` — new module (functions in §4).
- `agentpit/config.py` — `pinned_series` (+ parse), `pin_sync_enabled` (validator
  default = `sync_enabled`), `pin_sync_offset_seconds`.
- `agentpit/api/app.py` — `_run_pin_sync`, `_pin_sync_loop`, lifespan wiring.
- `.env.example` — document the new knobs.
- `tests/` — unit + DB + on-chain + wiring tests.

## 11. Deferred follow-ups (out of scope for v1)

- **Lookahead pre-sync** of the next window (prepare on-chain before it goes live) —
  needs a way to keep not-yet-live windows out of the liquidity mirror's active set.
- **Pruning** of accumulated resolved windows under a series event (DB size + long
  detail lists).
- **Frontend polish:** a proper series view (active window prominent + window switcher +
  collapsed resolved history) in `ui/`.
- **Auto-discovery** of high-volume series via `GET /series?order=volume24hr` (instead of
  the manual allow-list).
- *(Tracked separately, not part of this feature)* the Task-4 cheap-sync **self-heal**
  gap: already-synced markets are not re-prepared on-chain after an anvil/contract reset
  — currently handled operationally by `scripts/db_reset.sh`.
