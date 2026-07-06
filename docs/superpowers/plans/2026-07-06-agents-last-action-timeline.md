# /agents Last Action + Timeline Windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Last Action" column and 24h/7d/30d/All-time re-ranking tabs to the `/agents` Agent Arena leaderboard — UI-only, no bot or data-contract changes.

**Architecture:** Pure helpers in the existing arena data layer (`ui/src/api/leaderboard.ts`) compute the last trade from an agent's `bot-status-<id>.json` feed and derive a window-scoped agent from the `leaderboard.json` equity series; the page maps agents through `windowAgent` before the untouched `rankAgents`, so ranking/medals/sparklines follow the selected window for free.

**Tech Stack:** Vite + React + TypeScript, TanStack Query, Tailwind, vitest.

**Spec:** `docs/superpowers/specs/2026-07-06-agents-last-action-timeline-design.md`

## Global Constraints

- Repo `/Users/yavorsky/dev/agentpit`, branch `mvp`. All paths below are repo-relative.
- UI-only: do NOT touch anything under `agentpit/` (backend) or the agentpit-trader repo, and do NOT change the JSON shapes of `ui/public/leaderboard.json` / `bot-status-<id>.json`.
- The working tree holds unrelated user WIP (`ui/src/api/auth.ts`, `ui/src/api/markets.ts`, `ui/src/api/markets.test.ts`, `ui/src/auth/AuthContext.tsx`, `ui/src/pages/ProfilePage.tsx`, `ui/src/pages/SettingsPage.tsx`, backend files). NEVER `git add -A` / `git add .` — stage only the files this plan names.
- Git commits: NO `Co-Authored-By` / AI-attribution trailers.
- TDD: every task writes its failing test first and runs it before implementing.
- Test command (from `ui/`): `npx vitest run` (full suite) or `npx vitest run <file>` (one file). Typecheck: `npm run typecheck`. Suite is currently 105 green.
- Direction→outcome-label mapping everywhere: `UP` → `YES`, `DOWN` → `NO`, anything else → no side label.
- Window boundary rule: a close with `t === startTs` belongs to *before* the window (strictly-greater comparison for in-window points).

---

### Task 1: Export `relativeTime` from `lib/format.ts` (moved out of AgentPage)

**Files:**
- Modify: `ui/src/lib/format.ts`
- Modify: `ui/src/lib/format.test.ts`
- Modify: `ui/src/pages/AgentPage.tsx` (import line ~15; delete local fn at ~615-621)

**Interfaces:**
- Consumes: nothing new.
- Produces: `export function relativeTime(secsAgo: number): string` — `"42s" / "5m" / "2h" / "3d"`, negatives clamp to `"0s"`. Task 4 renders `` `${relativeTime(now - ts)} ago` ``.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/lib/format.test.ts` (and add `relativeTime` to the import from `./format`):

```ts
describe("relativeTime", () => {
  it("renders seconds under a minute", () => {
    expect(relativeTime(42)).toBe("42s");
  });

  it("renders whole minutes under an hour", () => {
    expect(relativeTime(5 * 60 + 30)).toBe("5m");
  });

  it("renders whole hours under a day", () => {
    expect(relativeTime(2 * 3600 + 59 * 60)).toBe("2h");
  });

  it("renders whole days from 24h up", () => {
    expect(relativeTime(3 * 86_400 + 5)).toBe("3d");
  });

  it("clamps negative input (clock skew) to 0s", () => {
    expect(relativeTime(-7)).toBe("0s");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/lib/format.test.ts`
Expected: FAIL — `relativeTime` is not exported by `./format`.

- [ ] **Step 3: Implement — move the function verbatim**

Append to `ui/src/lib/format.ts`:

```ts
/** "42s" / "5m" / "2h" / "3d" — coarse age of an event given its distance in
 *  seconds. Negative distances (clock skew) clamp to "0s". Callers append
 *  their own "ago". */
export function relativeTime(secsAgo: number): string {
  if (secsAgo < 0) secsAgo = 0;
  if (secsAgo < 60) return `${secsAgo}s`;
  if (secsAgo < 3600) return `${Math.floor(secsAgo / 60)}m`;
  if (secsAgo < 86_400) return `${Math.floor(secsAgo / 3600)}h`;
  return `${Math.floor(secsAgo / 86_400)}d`;
}
```

In `ui/src/pages/AgentPage.tsx`:
1. Change the format import (currently `import { formatClock, formatCountdown } from "@/lib/format";`) to:

```ts
import { formatClock, formatCountdown, relativeTime } from "@/lib/format";
```

2. Delete the now-duplicate private function near the bottom of the file (keep `shortAddr` above it):

```ts
function relativeTime(secsAgo: number): string {
  if (secsAgo < 0) secsAgo = 0;
  if (secsAgo < 60) return `${secsAgo}s`;
  if (secsAgo < 3600) return `${Math.floor(secsAgo / 60)}m`;
  if (secsAgo < 86_400) return `${Math.floor(secsAgo / 3600)}h`;
  return `${Math.floor(secsAgo / 86_400)}d`;
}
```

- [ ] **Step 4: Run tests + typecheck to verify green**

Run: `cd ui && npx vitest run src/lib/format.test.ts && npm run typecheck`
Expected: PASS (existing format tests + 5 new), typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/lib/format.ts ui/src/lib/format.test.ts ui/src/pages/AgentPage.tsx
git commit -m "refactor(ui): export relativeTime from lib/format, drop AgentPage copy"
```

---

### Task 2: `lastTrade` helper in the arena data layer

**Files:**
- Modify: `ui/src/api/leaderboard.ts`
- Modify: `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Consumes: `BotFeedItem` from `@/api/botStatus` (fields used: `ts: number`, `decision_id: string`, `traded: boolean`; display fields `title`, `direction` pass through untouched).
- Produces: `export function lastTrade(feed: BotFeedItem[]): BotFeedItem | null` — newest item with `traded === true` by `(ts, decision_id)`; `null` when none. Task 4 calls it with `useBotStatus(agentId).data.feed`.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/api/leaderboard.test.ts`. Add to the top of the file:

```ts
import { lastTrade } from "./leaderboard"; // fold into the existing ./leaderboard import list
import type { BotFeedItem } from "./botStatus";
```

then below the existing `agent()` factory:

```ts
function feedItem(over: Partial<BotFeedItem>): BotFeedItem {
  return {
    ts: 0,
    cycle_id: "c",
    decision_id: "d-0",
    title: "Q?",
    direction: "UP",
    recent_move: 0,
    rationale: "",
    edge_source: "model",
    outcome: "traded",
    traded: true,
    demo: false,
    side: "BUY",
    price: 0.5,
    size: 10,
    ...over,
  };
}

describe("lastTrade", () => {
  it("returns null for an empty feed", () => {
    expect(lastTrade([])).toBeNull();
  });

  it("returns null when no item actually traded", () => {
    expect(
      lastTrade([feedItem({ traded: false, outcome: "no_trade" })]),
    ).toBeNull();
  });

  it("picks the newest traded item even from an unsorted feed, skipping non-trades", () => {
    const older = feedItem({ ts: 100, decision_id: "d-1" });
    const newest = feedItem({ ts: 300, decision_id: "d-2" });
    const heldLater = feedItem({
      ts: 400,
      decision_id: "d-3",
      traded: false,
      outcome: "no_trade",
    });
    expect(lastTrade([older, heldLater, newest])).toEqual(newest);
  });

  it("breaks equal timestamps by decision_id", () => {
    const a = feedItem({ ts: 100, decision_id: "d-1" });
    const b = feedItem({ ts: 100, decision_id: "d-9" });
    expect(lastTrade([a, b])).toEqual(b);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/api/leaderboard.test.ts`
Expected: FAIL — `lastTrade` is not exported by `./leaderboard`.

- [ ] **Step 3: Implement**

In `ui/src/api/leaderboard.ts`, extend the existing botStatus import (line 2) to:

```ts
import { BOT_ADDRESS, type BotFeedItem, type PnlPoint } from "@/api/botStatus";
```

and append:

```ts
/** Newest feed item that actually traded, or null. Does not trust feed order:
 *  picks the max (ts, decision_id) among traded items. */
export function lastTrade(feed: BotFeedItem[]): BotFeedItem | null {
  let best: BotFeedItem | null = null;
  for (const item of feed) {
    if (!item.traded) continue;
    if (
      best === null ||
      item.ts > best.ts ||
      (item.ts === best.ts && item.decision_id > best.decision_id)
    ) {
      best = item;
    }
  }
  return best;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/api/leaderboard.test.ts`
Expected: PASS (existing leaderboard tests + 4 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/api/leaderboard.ts ui/src/api/leaderboard.test.ts
git commit -m "feat(ui): lastTrade helper — newest traded feed item for the arena hub"
```

---

### Task 3: `TIME_WINDOWS` + `windowAgent` window math

**Files:**
- Modify: `ui/src/api/leaderboard.ts`
- Modify: `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Consumes: `LeaderboardAgent` (existing; `equity: PnlPoint[]` is a cumulative realized-P&L step function sorted ascending by `t`, anchored at `{t:0,p:0}`; `unrealized_pnl` is "now"-only).
- Produces (Task 4 relies on these exact names):
  - `export type TimeWindowKey = "24h" | "7d" | "30d" | "all"`
  - `export interface TimeWindow { key: TimeWindowKey; label: string; seconds: number | null }`
  - `export const TIME_WINDOWS: TimeWindow[]` — `[{24h,86_400}, {7d,604_800}, {30d,2_592_000}, {all,null}]`
  - `export function windowAgent(agent: LeaderboardAgent, startTs: number | null): LeaderboardAgent` — `null` start returns the same object reference; otherwise a new agent with window-scoped `realized_pnl`, `total_pnl`, `trades`, `equity` (rebased to 0 at `startTs`).

- [ ] **Step 1: Write the failing test**

Append to `ui/src/api/leaderboard.test.ts` (add `TIME_WINDOWS`, `windowAgent` to the `./leaderboard` import):

```ts
describe("TIME_WINDOWS", () => {
  it("offers 24h/7d/30d/all with correct lengths", () => {
    expect(TIME_WINDOWS.map((w) => w.key)).toEqual(["24h", "7d", "30d", "all"]);
    expect(TIME_WINDOWS.map((w) => w.seconds)).toEqual([
      86_400, 604_800, 2_592_000, null,
    ]);
  });
});

describe("windowAgent", () => {
  const base = agent({
    realized_pnl: -20,
    unrealized_pnl: -5,
    trades: 3,
    total_pnl: -25,
    equity: [
      { t: 0, p: 0 },
      { t: 1000, p: -8 },
      { t: 2000, p: -12 },
      { t: 3000, p: -20 },
    ],
  });

  it("returns the same agent object for All time (null start)", () => {
    expect(windowAgent(base, null)).toBe(base);
  });

  it("re-scopes realized, total, trades, and equity to the window", () => {
    const w = windowAgent(base, 1500);
    expect(w.realized_pnl).toBe(-12); // -20 now minus -8 at window start
    expect(w.total_pnl).toBe(-17); // window realized + unrealized -5
    expect(w.trades).toBe(2); // closes at t=2000 and t=3000
    expect(w.equity).toEqual([
      { t: 1500, p: 0 },
      { t: 2000, p: -4 },
      { t: 3000, p: -12 },
    ]);
  });

  it("treats a close exactly at the boundary as before the window", () => {
    const w = windowAgent(base, 2000);
    expect(w.trades).toBe(1); // only t=3000
    expect(w.realized_pnl).toBe(-8); // -20 minus -12
    expect(w.equity).toEqual([
      { t: 2000, p: 0 },
      { t: 3000, p: -8 },
    ]);
  });

  it("keeps unrealized P&L in every window", () => {
    const w = windowAgent(base, 999_999); // window starts after all closes
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(-5);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 999_999, p: 0 }]);
  });

  it("handles a fresh agent that only has the zero anchor", () => {
    const fresh = agent({ equity: [{ t: 0, p: 0 }] });
    const w = windowAgent(fresh, 500);
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(0);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 500, p: 0 }]);
  });

  it("handles an empty equity series", () => {
    const empty = agent({ equity: [], unrealized_pnl: 2 });
    const w = windowAgent(empty, 500);
    expect(w.realized_pnl).toBe(0);
    expect(w.total_pnl).toBe(2);
    expect(w.trades).toBe(0);
    expect(w.equity).toEqual([{ t: 500, p: 0 }]);
  });

  it("does not mutate the input agent", () => {
    const snapshot = JSON.parse(JSON.stringify(base));
    windowAgent(base, 1500);
    expect(base).toEqual(snapshot);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/api/leaderboard.test.ts`
Expected: FAIL — `TIME_WINDOWS` / `windowAgent` not exported.

- [ ] **Step 3: Implement**

Append to `ui/src/api/leaderboard.ts`:

```ts
export type TimeWindowKey = "24h" | "7d" | "30d" | "all";

export interface TimeWindow {
  key: TimeWindowKey;
  label: string;
  /** Window length in seconds; null = all time. */
  seconds: number | null;
}

/** Rolling leaderboard windows (not calendar days) — steadier for a demo. */
export const TIME_WINDOWS: TimeWindow[] = [
  { key: "24h", label: "24h", seconds: 86_400 },
  { key: "7d", label: "7d", seconds: 604_800 },
  { key: "30d", label: "30d", seconds: 2_592_000 },
  { key: "all", label: "All time", seconds: null },
];

/** Derive an agent re-scoped to [startTs, now]. `equity` is a cumulative
 *  realized-P&L step function (ascending t, `{t:0,p:0}` anchor), so the
 *  window's realized P&L is the step delta across the boundary; unrealized is
 *  "now"-only and counts toward every window. A close exactly at `startTs`
 *  belongs to *before* the window. `startTs === null` (All time) returns the
 *  agent unchanged so ranking stays byte-identical to today. */
export function windowAgent(
  agent: LeaderboardAgent,
  startTs: number | null,
): LeaderboardAgent {
  if (startTs === null) return agent;
  const realizedNow = agent.equity.length
    ? agent.equity[agent.equity.length - 1].p
    : 0;
  let realizedAtStart = 0;
  for (const pt of agent.equity) {
    if (pt.t <= startTs) realizedAtStart = pt.p;
  }
  const inWindow = agent.equity.filter((pt) => pt.t > startTs);
  const realized = realizedNow - realizedAtStart;
  return {
    ...agent,
    realized_pnl: realized,
    total_pnl: realized + agent.unrealized_pnl,
    trades: inWindow.length,
    equity: [
      { t: startTs, p: 0 },
      ...inWindow.map((pt) => ({ t: pt.t, p: pt.p - realizedAtStart })),
    ],
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/api/leaderboard.test.ts`
Expected: PASS (all leaderboard tests, incl. Task 2's).

- [ ] **Step 5: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/api/leaderboard.ts ui/src/api/leaderboard.test.ts
git commit -m "feat(ui): TIME_WINDOWS + windowAgent — client-side window math over equity series"
```

---

### Task 4: Arena page — window tabs + Last Action column

**Files:**
- Modify: `ui/src/pages/AgentArenaPage.tsx`

**Interfaces:**
- Consumes: `lastTrade`, `TIME_WINDOWS`, `windowAgent`, `type TimeWindowKey` (Tasks 2-3, from `@/api/leaderboard`); `relativeTime` (Task 1, from `@/lib/format`); existing `useBotStatus` from `@/api/botStatus`, `rankAgents`, `useNowSeconds`.
- Produces: final UI; no downstream consumers.

No new unit tests: the page has no test file today and all new logic lives in the already-tested helpers; this task is wiring + markup (verified by typecheck, lint, full suite, build).

- [ ] **Step 1: Update imports and page state**

In `ui/src/pages/AgentArenaPage.tsx`, replace the import block (lines 1-11) with:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import {
  equityPoints,
  lastTrade,
  rankAgents,
  TIME_WINDOWS,
  useLeaderboard,
  windowAgent,
  type RankedAgent,
  type TimeWindowKey,
} from "@/api/leaderboard";
import { useBotStatus } from "@/api/botStatus";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { formatCountdown, formatSignedUsd, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
```

Inside `AgentArenaPage()`, replace

```tsx
  const { data, error } = useLeaderboard();
  const agents = data ? rankAgents(data.agents) : [];
```

with

```tsx
  const { data, error } = useLeaderboard();
  const [windowKey, setWindowKey] = useState<TimeWindowKey>("all");
  const win =
    TIME_WINDOWS.find((w) => w.key === windowKey) ??
    TIME_WINDOWS[TIME_WINDOWS.length - 1];
  const startTs = win.seconds === null ? null : now - win.seconds;
  const agents = data
    ? rankAgents(data.agents.map((a) => windowAgent(a, startTs)))
    : [];
```

- [ ] **Step 2: Add the window tabs between the header and the table**

Directly after the closing `</header>` tag, insert:

```tsx
      <div
        className="flex w-fit items-center gap-1 rounded-full bg-muted p-1"
        aria-label="Leaderboard time window"
      >
        {TIME_WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            aria-pressed={w.key === windowKey}
            onClick={() => setWindowKey(w.key)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold transition-colors",
              w.key === windowKey
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {w.label}
          </button>
        ))}
      </div>
```

- [ ] **Step 3: Add the Last Action column (lg+) to the table header and rows**

Table header — replace the header-row `div` with (note the added `lg:grid-cols` variant and the Last Action label):

```tsx
          <div className="hidden grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid lg:grid-cols-[3rem_minmax(0,1fr)_minmax(0,16rem)_8rem_7rem_4rem]">
            <span>#</span>
            <span>Agent</span>
            <span className="hidden lg:block">Last Action</span>
            <span className="text-right">Total P&amp;L</span>
            <span className="text-center">Equity</span>
            <span className="text-right">Trades</span>
          </div>
```

Row rendering — pass `now` down: change the map call to

```tsx
              agents.map((a) => <AgentRow key={a.id} agent={a} now={now} />)
```

and replace the whole `AgentRow` component with:

```tsx
function AgentRow({ agent, now }: { agent: RankedAgent; now: number }) {
  return (
    <li>
      <Link
        to={`/agents/${agent.id}`}
        className="grid grid-cols-[3rem_minmax(0,1fr)_8rem] items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50 sm:grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] lg:grid-cols-[3rem_minmax(0,1fr)_minmax(0,16rem)_8rem_7rem_4rem]"
      >
        <span className="text-lg tabular-nums">
          {agent.medal ?? (
            <span className="text-muted-foreground">{agent.rank}</span>
          )}
        </span>
        <span className="flex min-w-0 items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-background text-xl">
            {agent.emoji}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-semibold">{agent.name}</span>
            <span className="block truncate text-xs text-muted-foreground">
              {agent.style}
            </span>
          </span>
        </span>
        <LastActionCell agentId={agent.id} now={now} />
        <span
          className={cn(
            "text-right text-base font-semibold tabular-nums",
            pnlText(agent.total_pnl),
          )}
        >
          {formatSignedUsd(agent.total_pnl)}
        </span>
        <span className="hidden justify-center sm:flex">
          <Sparkline
            points={equityPoints(agent.equity)}
            width={96}
            height={28}
            tone={pnlTone(agent.total_pnl)}
          />
        </span>
        <span className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block">
          {agent.trades}
        </span>
      </Link>
    </li>
  );
}

/** Latest trade for one agent, off its bot-status feed. Fail-soft by design:
 *  a missing/stale status file or a trade-less feed renders a quiet dash —
 *  one agent's file must never break the whole row. */
function LastActionCell({ agentId, now }: { agentId: string; now: number }) {
  const { data } = useBotStatus(agentId);
  const trade = data ? lastTrade(data.feed) : null;
  if (!trade) {
    return (
      <span className="hidden text-sm text-muted-foreground lg:block">—</span>
    );
  }
  const side =
    trade.direction === "UP" ? "YES" : trade.direction === "DOWN" ? "NO" : null;
  return (
    <span className="hidden min-w-0 lg:block">
      <span className="block truncate text-sm">
        <span className="font-medium">
          Trade{side ? ` "${side}"` : ""}
        </span>
        <span className="text-muted-foreground"> · {trade.title}</span>
      </span>
      <span className="block text-xs tabular-nums text-muted-foreground">
        {relativeTime(now - trade.ts)} ago
      </span>
    </span>
  );
}
```

(Everything else in the file — header, live badge, error state — stays untouched. Note: the Last Action grid cell exists at every breakpoint but its contents are `hidden` below `lg`; below `lg` the sm/mobile grids don't allocate a track for it, and CSS grid simply doesn't place a fully-hidden child, so the layouts stay as today.)

- [ ] **Step 4: Verify — full suite, typecheck, lint, build**

Run: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all pass; vitest total = previous count + new tests from Tasks 1-3, 0 failures.

- [ ] **Step 5: Visual sanity check (only if the Vite dev server is already running)**

If `http://localhost:5173` responds, open `/agents` and confirm: tabs render with **All time** active and numbers identical to before; switching to **24h** re-ranks and rebases sparklines; each traded agent shows `Trade "YES|NO" · <title>` + `Nh ago`; a trade-less agent (Cautious) shows `—`. If the dev server is not running, skip — do NOT start servers.

- [ ] **Step 6: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/pages/AgentArenaPage.tsx
git commit -m "feat(ui): arena hub — Last Action column + 24h/7d/30d/all window tabs"
```
