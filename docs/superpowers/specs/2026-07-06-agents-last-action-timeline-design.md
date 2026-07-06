# /agents Page: Last Action + Timeline Windows — Design

**Date:** 2026-07-06 · **Branch:** `mvp` · **Status:** approved by user ("норм")

## Goal

Liven up the `/agents` Agent Arena leaderboard: show each agent's most recent
trade ("Last Action") and let the board be re-ranked over a time window
(24h · 7d · 30d · All time). **UI-only** — no changes to the agentpit-trader
bot or the JSON data contract.

## Data sources (existing, unchanged)

- `ui/public/bot-status-<id>.json` — per agent, already fetched by
  `useBotStatus(agentId)` (`ui/src/api/botStatus.ts`). Its `feed` holds the
  last 50 decisions: `ts, title, direction (UP|DOWN|NONE), traded, side,
  price, size, …`. Only position **opens** appear in the feed (closes are not
  published) — accepted limitation, chosen explicitly by the user.
- `ui/public/leaderboard.json` — per agent `equity: [{t, p}]` = cumulative
  **realized** P&L stamped at each close (`exit_ts`), anchored with a
  `{t: 0, p: 0}` baseline point; plus `realized_pnl`, `unrealized_pnl`
  (marked to book mid, "now"-only), `total_pnl`, `trades`, `open_positions`.

## Feature 1: Last Action column

**Where:** `AgentArenaPage` row, new column between "Agent" and "Total P&L".
Visible from the `lg` breakpoint; below `lg` the row renders exactly as today
(the grid at `sm` is already tight inside `max-w-5xl`).

**Data flow:** each `AgentRow` calls the existing `useBotStatus(agent.id)`
hook (react-query keys per agent; 4s poll of a tiny same-origin static file —
same cadence the detail page already uses).

**New pure helper** in `ui/src/api/leaderboard.ts`:

```ts
/** Newest feed item that actually traded, or null. Does not trust feed order:
 *  picks max (ts, decision_id). */
export function lastTrade(feed: BotFeedItem[]): BotFeedItem | null;
```

**Rendering (two lines):**

- Line 1: `Trade "YES" · <title>` — direction `UP` → `YES`, `DOWN` → `NO`;
  any other direction renders `Trade · <title>` (no quoted side). Title
  truncates with ellipsis (`truncate`, `min-w-0`).
- Line 2: relative age, muted: `2h ago` — computed from `item.ts` and
  `useNowSeconds()`.

**Relative time helper:** extract the private `relativeTime(secsAgo)` from
`ui/src/pages/AgentPage.tsx:615` into `ui/src/lib/format.ts` (exported,
same behavior: `42s / 5m / 2h / 3d`, negatives clamp to 0); AgentPage imports
it, local copy deleted. The cell renders `` `${relativeTime(now - ts)} ago` ``.

**Fail-soft:** status file loading/error, empty feed, or no traded item →
render a muted `—` (the row must never break because one agent's status file
is missing).

## Feature 2: Timeline windows

**UI:** segmented control above the table: **24h · 7d · 30d · All time**.
Rolling windows (not calendar days) — agreed with the user. Default:
**All time**. Local `useState` only, no URL param. Styling follows the page's
existing pill/badge patterns (`cn`, border, rounded, muted for inactive).

**New pure helpers** in `ui/src/api/leaderboard.ts`:

```ts
export type TimeWindowKey = "24h" | "7d" | "30d" | "all";
export const TIME_WINDOWS: { key: TimeWindowKey; label: string; seconds: number | null }[];
// [{key:"24h", label:"24h", seconds:86_400}, {key:"7d", …, 604_800},
//  {key:"30d", …, 2_592_000}, {key:"all", label:"All time", seconds:null}]

/** Derive an agent re-scoped to the window [startTs, now]. "all" (startTs
 *  null) returns the agent unchanged. */
export function windowAgent(agent: LeaderboardAgent, startTs: number | null): LeaderboardAgent;
```

**Window math** (equity is a cumulative step function of realized P&L):

- `realizedNow` = `p` of the last equity point (0 if the series is empty).
- `realizedAtStart` = `p` of the last point with `t <= startTs`, default 0.
  (The `{t:0}` baseline always satisfies `t <= startTs`, so a real epoch
  start never misses the anchor.)
- `realized_pnl` (window) = `realizedNow − realizedAtStart`.
- `total_pnl` (window) = window realized + `agent.unrealized_pnl` — open
  positions are "current" and count toward every window.
- `trades` (window) = count of points with `t > startTs` (strictly greater:
  a close exactly at the boundary belongs to "before").
- `equity` (window) = `[{t: startTs, p: 0}, …points with t > startTs mapped
  p → p − realizedAtStart]` — rebased to 0 at window start so the sparkline
  shows the window's move. No points in window → the single anchor point
  (`equityPoints()` already pads to a flat line).

**Ranking:** the page maps agents through `windowAgent` and feeds the result
to the existing `rankAgents()` — medals, order, P&L colors, and sparklines
all follow the selected window with no changes to `rankAgents`. `All time`
is byte-identical to today's behavior.

**Note (expected, not a bug):** while the arena is younger than the window
lengths, 24h/7d/30d show the same numbers; the tabs diverge as history
accumulates.

## Files

- Modify `ui/src/api/leaderboard.ts` — `lastTrade`, `TimeWindowKey`,
  `TIME_WINDOWS`, `windowAgent` (import `BotFeedItem` from `@/api/botStatus`).
- Modify `ui/src/api/leaderboard.test.ts` — unit tests (below).
- Modify `ui/src/pages/AgentArenaPage.tsx` — window tabs state + Last Action
  cell (grid columns gain a `lg:` variant).
- Modify `ui/src/lib/format.ts` — export `relativeTime` (moved from
  AgentPage); `ui/src/lib/format.test.ts` (exists) gains its cases.
- Modify `ui/src/pages/AgentPage.tsx` — import `relativeTime`, drop local copy.

## Testing (vitest, data-layer; no page-level tests, consistent with suite)

- `lastTrade`: empty feed → null; no `traded:true` → null; picks newest by
  `ts` even when input is unsorted; `decision_id` tiebreak on equal `ts`.
- `windowAgent`: `startTs null` → same object back (identity); boundary point
  `t === startTs` excluded from trades but sets `realizedAtStart`; rebasing
  (window `total_pnl`/`equity` correct vs hand-computed); empty equity;
  fresh agent with only `{t:0,p:0}`; unrealized added to every window.
- `relativeTime`: `42s`, `5m`, `2h`, `3d`, negative → `0s`.

## Error handling

- Per-row bot-status failure → `—` in the Last Action cell only.
- Leaderboard fetch failure → unchanged existing empty/error state.

## Out of scope (explicit)

- Position **closes** in Last Action (needs a bot-side contract change).
- held/skipped decisions in Last Action (user chose trades-only).
- Calendar-day windows, URL-persisted window state, bot-side per-window P&L.
