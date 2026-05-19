# Event-Detail Charts — Design

**Date:** 2026-05-19
**Scope:** Frontend-only. Add a 24h price chart to the top of the event detail page. Single-outcome events show one line; multi-outcome events overlay the top 4 markets by current chance.

## Goals

- A user landing on `/events/:slug` immediately sees how prices have moved over the last 24 hours.
- Single-market events (e.g. *Xi Jinping out before 2027?*) show one line.
- Multi-market events (e.g. *Democratic Presidential Nominee 2028*, *2026 FIFA World Cup Winner*) show the **top 4 markets by current chance** on a single chart with distinct colors and a compact legend.
- Reuses the existing `/sparkline/{market_id}/{outcome}` endpoint — no backend changes.
- Static rendering only — no hover crosshair, no time-window selector. Both are explicitly deferred.

## Non-goals

- Hover tooltips / crosshair (deferred, easy to add on top later).
- Time-window selector (24h / 7d / 30d pills). Window is fixed at 24h.
- Per-row sparkline inside `EventLeaderboardRow` (out of scope — chart is at the top, not per row).
- Bundling sparkline data into `/events` to reduce fan-out — that's Phase 3 of the snapshot work and ships separately.
- Charts on `MarketDetailPage` — also separate scope.

## Architecture

Three new frontend pieces, plus an edit to `EventDetailPage`:

```
src/
  lib/
    chartGeometry.ts        ← smoothPath + projection helpers (extracted from Sparkline)
    chartGeometry.test.ts   ← TDD'd
    eventChartSeries.ts     ← pickChartSeries(markets, midByMarket, palette, n)
    eventChartSeries.test.ts ← TDD'd
  components/
    EventChart.tsx          ← orchestrator: picks markets, fetches sparklines, renders MultiSparkline or empty state
    MultiSparkline.tsx      ← pure SVG renderer: gridlines + N smoothed paths + last-point dots
  pages/
    EventDetailPage.tsx     ← inserts <EventChart /> between header and the columns
  components/
    Sparkline.tsx           ← refactored to consume chartGeometry.smoothPath (no behavior change)
```

No new dependencies.

## Visual & placement

- Section sits **between the event header and the column layout** (full width on lg+ screens, full width on mobile).
- Height: ~180px on the SVG; the section's outer rounded card adds ~24px of padding on each side.
- Header strip above the chart:
  - Left: small mono caption `24h trend`
  - Right: legend chips, one per visible series — `● Outcome name 32%`
- Subtle horizontal gridlines at y = 25 / 50 / 75 % (interior only — the top and bottom edges of the chart already represent 0 and 100). Foreground at 4% opacity.
- Y-axis is fixed at `[0, 1]` (i.e. 0% – 100%). This makes all charts directly comparable.
- X-axis is implicit (no labels) — duration is communicated by the `24h` caption.
- Empty state: when fewer than 2 total points across all series, replace the chart area with a centered `No price history yet` message.

## Series selection (multi-market)

The top 4 markets are picked by current YES mid, descending:

```
const ranked = sortMarketsByYesMid(markets, midByMarket);  // existing helper
const top    = ranked.slice(0, 4);
```

Colors are assigned by rank, using a fixed 4-color palette:

| Rank | Color (Tailwind) | Hex used in SVG |
|------|------------------|------------------|
| #1   | `emerald-500`    | #10b981 |
| #2   | `sky-500`        | #0ea5e9 |
| #3   | `amber-500`      | #f59e0b |
| #4   | `rose-500`       | #f43f5e |

Single-market events get one series in `emerald-500` (regardless of up/down direction — we considered tone-coloring but it'd diverge from multi-market and add a special case for no upside).

## Data flow

```
EventDetailPage
 └─ <EventChart event={event} markets={markets} midByMarket={midByMarket} />
      ↓ picks top N markets via pickChartSeries()
      ↓ useSparkline(market_id, "Yes") × N — parallel, deduped by react-query
      ↓ merges responses → series: { label, color, points: [{t,p}] }[]
      ↓ if total points < 2 → <EmptyState />
      └─ <MultiSparkline series={series} width={…} height={…} />
```

For **single-market** events, `pickChartSeries` returns one entry — the renderer doesn't need to branch.

`midByMarket` is already computed at the `EventDetailPage` level via `useYesMidMap` (used today to sort the leaderboard). We pass it down; no extra fetches.

## Edge cases

- **A market in the top 4 has no points yet:** still appears in legend, no line is drawn for it. Other lines render normally.
- **All visible markets are empty:** the chart area is replaced by the empty-state placeholder. Legend is hidden.
- **Fewer than 4 markets in the event:** render whatever count exists. The palette is sliced to match — never wraps.
- **A market has exactly 1 point:** treated as a degenerate series — last-point dot only, no path.
- **Y values out of expected range:** never happens (prices in `[0, 1]` are enforced upstream), but `projectToViewBox` clamps defensively.

## Testing

Pure functions covered by TDD:

| Function | Test cases |
|----------|------------|
| `smoothPath(coords)` | empty → `""`; single point → `"M x y"`; two points → straight curve; N points → control points stay between adjacent samples |
| `projectToViewBox(points, w, h)` | min/max projection, clamping when price is out of `[0,1]`, padding respected |
| `pickChartSeries(markets, midByMarket, palette, n)` | sorts by descending mid, slices to n, assigns palette in order, handles fewer-than-n markets, handles missing mids (tied-last) |

`EventChart` rendering itself (legend matches series, empty state shows when expected, correct N markets picked) is verified via Playwright screenshots against the running dev server. No React Testing Library setup is added in this scope.

## Out-of-scope: future hooks

- **Hover crosshair**: would add `MouseMove`-driven vertical line + tooltip listing all series' prices at the hovered timestamp. ~1 day of work on top of this design. Adds React state but no new data shape.
- **Time-window selector**: adds a `windowHours` prop to `useSparkline` and three cached queries per series. Backend `/sparkline` already accepts `window_hours` — no API change.
- **Phase 3 bundling**: replaces the N parallel `useSparkline` calls with a single value pulled from the `/events` response. Drop-in for the `EventChart` data layer; `MultiSparkline` is unaffected.
