# Agent Arena Leaderboard — UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/agents` Agent Arena hub page to the agentpit UI that ranks the five news-bot personality variants by live Total P&L, with click-through to a per-agent detail view that reuses the existing AgentPage.

**Architecture:** The bot side is already built and live — it writes `ui/public/leaderboard.json` (the aggregate) and one `ui/public/bot-status-<id>.json` per agent (same shape as the existing single-bot `bot-status.json`) every cycle. This plan is **UI-only**: a new data hook + ranking helper read `leaderboard.json`; a new `AgentArenaPage` renders the ranked rows; the existing `AgentPage` is parameterized by an `agentId` route param so each row drills into a reused detail view. No backend or bot changes.

**Tech Stack:** React 18 + TypeScript, Vite, React Router v6 (`react-router-dom`), TanStack Query v5, Tailwind, Vitest (environment `node`, pure-function tests — the codebase has **no** component-render tests; logic lives in `api/`/`lib/` and is unit-tested there).

## Global Constraints

- **Repo + branch:** all work is in `/Users/yavorsky/dev/agentpit` on branch `mvp`. The bot side lives in a separate repo (`agentpit-trader`) and is DONE — out of scope here.
- **Commit attribution:** do **NOT** add a `Co-Authored-By: Claude` trailer (or any Claude attribution) to commits. Plain Conventional-Commit subjects only.
- **Stage explicit paths only — never `git add -A`/`git add .`:** the working tree has unrelated, uncommitted UI demo-polish changes (`AgentPage.tsx`, `SettingsPage.tsx`, `ProfilePage.tsx`, `AuthContext.tsx`, `api/auth.ts`, `lib/format.ts`, `api/botStatus.ts`, etc.). Each task's commit must `git add` only the exact files that task lists. Do not sweep the tree.
- **Data contract is fixed (read-only).** The UI must consume these shapes exactly as the bot writes them; do not propose changing the bot. Verbatim samples live at `ui/public/leaderboard.json` and `ui/public/bot-status-bold.json`.
  - `leaderboard.json`: `{ updated_at: number (unix s), cycle_interval_minutes: number, agents: Agent[] }` where each `Agent` = `{ id, name, emoji, style, address, realized_pnl, unrealized_pnl, trades, open_positions, equity: {t:number,p:number}[], total_pnl }`. The file may already be sorted, but the **UI re-sorts defensively** (do not rely on file order).
  - `bot-status-<id>.json`: identical to the existing `BotStatus` shape in `ui/src/api/botStatus.ts` (`updated_at`, `cycle_interval_minutes`, `demo_mode`, `summary`, `pnl_series`, `feed`). It does **not** contain the agent's address — the address comes from `leaderboard.json`.
- **Ranking key:** Total P&L (`total_pnl` = realized + unrealized-to-mid) descending; 🥇🥈🥉 medals for the top three.
- **Routing decision (resolves the spec's open question):** `/agents` is the hub; `/agents/:agentId` is the per-agent detail; the legacy `/agent` route **redirects** to `/agents` (the old single-bot account `0x5b3D…` is now inactive, so a standalone `/agent` view would be permanently static).
- **Sparkline window:** the UI renders whatever points are in each agent's `equity` array as-is — no client-side time-windowing. (The bot owns the window.)
- **Verification commands (run from `ui/`):** `npm run test` (Vitest), `npm run typecheck` (`tsc -b --noEmit`), `npm run lint` (eslint), `npm run build`. After editing, report any new LSP/tsc diagnostics in the changed files.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ui/src/api/leaderboard.ts` | **create** | `LeaderboardData`/`LeaderboardAgent`/`RankedAgent`/`AgentIdentity` types; pure `rankAgents`, `resolveAgentIdentity`, `equityPoints`; `useLeaderboard()` query hook. |
| `ui/src/api/leaderboard.test.ts` | **create** | Unit tests for `rankAgents`, `resolveAgentIdentity`, `equityPoints`. |
| `ui/src/lib/format.ts` | modify | Add `formatSignedUsd(n)`. |
| `ui/src/lib/format.test.ts` | modify | Tests for `formatSignedUsd`. |
| `ui/src/api/botStatus.ts` | modify | Add `botStatusUrl(agentId?)`; parameterize `useBotStatus(agentId?)` (back-compatible). |
| `ui/src/api/botStatus.test.ts` | **create** | Tests for `botStatusUrl`. |
| `ui/src/lib/useNowSeconds.ts` | **create** | Extract the shared 1 Hz clock hook (used by both detail + hub pages). |
| `ui/src/pages/AgentPage.tsx` | modify | Consume `useNowSeconds` from the new module; parameterize by `agentId` (identity + per-agent status + per-agent positions + not-found state). |
| `ui/src/pages/AgentArenaPage.tsx` | **create** | The `/agents` hub: ranked rows from `leaderboard.json`, each linking to `/agents/:id`. |
| `ui/src/App.tsx` | modify | Add `/agents` + `/agents/:agentId` routes; redirect `/agent` → `/agents`. |
| `ui/src/components/TopNav.tsx` | modify | Point the live nav pill at `/agents`, relabel "Arena". |

**Build order rationale:** data layer (T1) → display primitive (T2) → per-agent status fetch (T3) → the detail route target (T4) → the hub that links into it (T5). The hub ships last so every row target already exists.

---

### Task 1: Leaderboard data layer (`leaderboard.ts`)

**Files:**
- Create: `ui/src/api/leaderboard.ts`
- Test: `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Consumes: `BOT_ADDRESS` and `PnlPoint` (already exported) from `ui/src/api/botStatus.ts`; `SparklineSample` from `ui/src/lib/chartGeometry.ts`.
- Produces:
  - `interface LeaderboardAgent { id; name; emoji; style; address; realized_pnl; unrealized_pnl; trades; open_positions; equity: PnlPoint[]; total_pnl }` (all numbers except the four leading strings).
  - `interface LeaderboardData { updated_at: number; cycle_interval_minutes: number; agents: LeaderboardAgent[] }`.
  - `interface RankedAgent extends LeaderboardAgent { rank: number; medal: string | null }`.
  - `function rankAgents(agents: LeaderboardAgent[]): RankedAgent[]`.
  - `interface AgentIdentity { address: string; name: string; emoji: string; style: string; isArena: boolean }`.
  - `const DEFAULT_IDENTITY: AgentIdentity`.
  - `type IdentityStatus = "default" | "loading" | "resolved" | "not-found"`.
  - `function resolveAgentIdentity(data: LeaderboardData | undefined, agentId: string | undefined): { identity: AgentIdentity | null; status: IdentityStatus }`.
  - `function equityPoints(equity: PnlPoint[]): SparklineSample[]`.
  - `function useLeaderboard()` — TanStack Query hook returning `LeaderboardData`.

- [ ] **Step 1: Write the failing tests**

Create `ui/src/api/leaderboard.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  DEFAULT_IDENTITY,
  equityPoints,
  rankAgents,
  resolveAgentIdentity,
  type LeaderboardAgent,
  type LeaderboardData,
} from "./leaderboard";

function agent(over: Partial<LeaderboardAgent>): LeaderboardAgent {
  return {
    id: "x",
    name: "X",
    emoji: "❓",
    style: "",
    address: "0xX",
    realized_pnl: 0,
    unrealized_pnl: 0,
    trades: 0,
    open_positions: 0,
    equity: [{ t: 0, p: 0 }],
    total_pnl: 0,
    ...over,
  };
}

describe("rankAgents", () => {
  it("orders by total_pnl descending and medals the top three", () => {
    const ranked = rankAgents([
      agent({ id: "a", name: "A", total_pnl: -10 }),
      agent({ id: "b", name: "B", total_pnl: 50 }),
      agent({ id: "c", name: "C", total_pnl: 5 }),
      agent({ id: "d", name: "D", total_pnl: -100 }),
    ]);
    expect(ranked.map((r) => r.id)).toEqual(["b", "c", "a", "d"]);
    expect(ranked.map((r) => r.rank)).toEqual([1, 2, 3, 4]);
    expect(ranked.map((r) => r.medal)).toEqual(["🥇", "🥈", "🥉", null]);
  });

  it("breaks ties by trades desc then name asc (stable at $0)", () => {
    const ranked = rankAgents([
      agent({ id: "z", name: "Zed", total_pnl: 0, trades: 2 }),
      agent({ id: "a", name: "Ann", total_pnl: 0, trades: 2 }),
      agent({ id: "m", name: "Moe", total_pnl: 0, trades: 9 }),
    ]);
    expect(ranked.map((r) => r.id)).toEqual(["m", "a", "z"]);
  });

  it("does not mutate the input array", () => {
    const input = [
      agent({ id: "a", total_pnl: 1 }),
      agent({ id: "b", total_pnl: 2 }),
    ];
    const snapshot = [...input];
    rankAgents(input);
    expect(input).toEqual(snapshot);
  });
});

describe("resolveAgentIdentity", () => {
  const data: LeaderboardData = {
    updated_at: 1,
    cycle_interval_minutes: 15,
    agents: [
      agent({
        id: "bold",
        name: "Bold",
        emoji: "🔥",
        style: "aggressive",
        address: "0xBold",
      }),
    ],
  };

  it("returns the single-bot default when no agentId is given", () => {
    const r = resolveAgentIdentity(data, undefined);
    expect(r.status).toBe("default");
    expect(r.identity).toEqual(DEFAULT_IDENTITY);
  });

  it("returns loading (null identity) while the leaderboard is undefined", () => {
    const r = resolveAgentIdentity(undefined, "bold");
    expect(r.status).toBe("loading");
    expect(r.identity).toBeNull();
  });

  it("resolves a matching agent's arena identity", () => {
    const r = resolveAgentIdentity(data, "bold");
    expect(r.status).toBe("resolved");
    expect(r.identity).toEqual({
      address: "0xBold",
      name: "Bold",
      emoji: "🔥",
      style: "aggressive",
      isArena: true,
    });
  });

  it("reports not-found for an unknown id in a loaded leaderboard", () => {
    const r = resolveAgentIdentity(data, "ghost");
    expect(r.status).toBe("not-found");
    expect(r.identity).toBeNull();
  });
});

describe("equityPoints", () => {
  it("passes through a curve that already has two or more points", () => {
    expect(
      equityPoints([
        { t: 0, p: 0 },
        { t: 5, p: 3 },
      ]),
    ).toEqual([
      { t: 0, p: 0 },
      { t: 5, p: 3 },
    ]);
  });

  it("pads a single point to a flat two-point line at its value", () => {
    expect(equityPoints([{ t: 0, p: 4 }])).toEqual([
      { t: 0, p: 4 },
      { t: 1, p: 4 },
    ]);
  });

  it("pads an empty curve to a flat zero line", () => {
    expect(equityPoints([])).toEqual([
      { t: 0, p: 0 },
      { t: 1, p: 0 },
    ]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npm run test -- src/api/leaderboard.test.ts`
Expected: FAIL — `Cannot find module './leaderboard'` (the module does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `ui/src/api/leaderboard.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { BOT_ADDRESS, type PnlPoint } from "@/api/botStatus";
import type { SparklineSample } from "@/lib/chartGeometry";

/**
 * The arena's aggregate, written by agentpit-trader into the UI's `public/`
 * each cycle (same same-origin static bridge as `useBotStatus`). `total_pnl`
 * = realized + unrealized (marked to book mid) and is the ranking key;
 * `equity` is that agent's cumulative-P/L curve for the sparkline.
 */
export interface LeaderboardAgent {
  id: string;
  name: string;
  emoji: string;
  style: string;
  address: string;
  realized_pnl: number;
  unrealized_pnl: number;
  trades: number;
  open_positions: number;
  equity: PnlPoint[];
  total_pnl: number;
}

export interface LeaderboardData {
  updated_at: number; // unix seconds
  cycle_interval_minutes: number;
  agents: LeaderboardAgent[];
}

/** An agent with its computed standing. `medal` is the 🥇/🥈/🥉 glyph for the
 *  top three, else null. */
export interface RankedAgent extends LeaderboardAgent {
  rank: number;
  medal: string | null;
}

const MEDALS = ["🥇", "🥈", "🥉"];

/** Rank agents by Total P&L (desc). Deterministic tiebreak — trades desc, then
 *  name asc — so equal-P/L agents (e.g. all $0 at launch) hold a stable order
 *  instead of jittering between polls. Returns a new array; input untouched. */
export function rankAgents(agents: LeaderboardAgent[]): RankedAgent[] {
  return [...agents]
    .sort(
      (a, b) =>
        b.total_pnl - a.total_pnl ||
        b.trades - a.trades ||
        a.name.localeCompare(b.name),
    )
    .map((a, i) => ({ ...a, rank: i + 1, medal: MEDALS[i] ?? null }));
}

/** Identity used to render a detail hero + fetch that agent's positions. */
export interface AgentIdentity {
  address: string;
  name: string;
  emoji: string;
  style: string;
  isArena: boolean;
}

/** Fallback identity for the legacy (non-arena) single-bot detail view. */
export const DEFAULT_IDENTITY: AgentIdentity = {
  address: BOT_ADDRESS,
  name: "agentpit-trader",
  emoji: "🤖",
  style: "autonomous trading agent",
  isArena: false,
};

export type IdentityStatus = "default" | "loading" | "resolved" | "not-found";

/** Resolve the identity for a detail page from the leaderboard:
 *  - no `agentId`            → single-bot default (legacy view)
 *  - `agentId`, not loaded   → loading (identity null)
 *  - `agentId` found         → that agent's arena identity
 *  - `agentId` absent in a loaded leaderboard → not-found (identity null) */
export function resolveAgentIdentity(
  data: LeaderboardData | undefined,
  agentId: string | undefined,
): { identity: AgentIdentity | null; status: IdentityStatus } {
  if (!agentId) return { identity: DEFAULT_IDENTITY, status: "default" };
  if (!data) return { identity: null, status: "loading" };
  const a = data.agents.find((x) => x.id === agentId);
  if (!a) return { identity: null, status: "not-found" };
  return {
    identity: {
      address: a.address,
      name: a.name,
      emoji: a.emoji,
      style: a.style,
      isArena: true,
    },
    status: "resolved",
  };
}

/** Pad an equity curve to >= 2 points so a fresh agent (single $0 point) still
 *  renders a flat line instead of a lone dot. */
export function equityPoints(equity: PnlPoint[]): SparklineSample[] {
  if (equity.length >= 2) return equity.map((d) => ({ t: d.t, p: d.p }));
  const p = equity[0]?.p ?? 0;
  return [
    { t: 0, p },
    { t: 1, p },
  ];
}

/** Fetch the arena leaderboard off the UI origin's static `public/`. Cache-busted
 *  + polled every 4s so ranks visibly move during the demo. */
export function useLeaderboard() {
  return useQuery({
    queryKey: ["leaderboard"],
    queryFn: async (): Promise<LeaderboardData> => {
      const res = await fetch(`/leaderboard.json?t=${Date.now()}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`leaderboard ${res.status}`);
      return (await res.json()) as LeaderboardData;
    },
    refetchInterval: 4_000,
    staleTime: 2_000,
    retry: false,
  });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npm run test -- src/api/leaderboard.test.ts`
Expected: PASS (10 tests).

- [ ] **Step 5: Typecheck**

Run: `cd ui && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd ui
git add src/api/leaderboard.ts src/api/leaderboard.test.ts
git commit -m "feat(ui): leaderboard data layer — rank + identity + equity helpers"
```

---

### Task 2: Signed-currency formatter (`formatSignedUsd`)

**Files:**
- Modify: `ui/src/lib/format.ts`
- Test: `ui/src/lib/format.test.ts`

**Interfaces:**
- Produces: `function formatSignedUsd(n: number): string` — `"+$84.20"` / `"-$210.80"` / `"$0.00"`.

- [ ] **Step 1: Write the failing tests**

In `ui/src/lib/format.test.ts`, change the import on line 2 to include `formatSignedUsd`:

```ts
import { formatProbabilityPct, formatSignedUsd, parseVolume } from "./format";
```

Then append this `describe` block at the end of the file:

```ts
describe("formatSignedUsd", () => {
  it("prefixes a positive amount with +", () => {
    expect(formatSignedUsd(84.2)).toBe("+$84.20");
  });

  it("prefixes a negative amount with -", () => {
    expect(formatSignedUsd(-210.8)).toBe("-$210.80");
  });

  it("renders zero without a sign", () => {
    expect(formatSignedUsd(0)).toBe("$0.00");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npm run test -- src/lib/format.test.ts`
Expected: FAIL — `formatSignedUsd is not a function` (or an import error).

- [ ] **Step 3: Write the implementation**

In `ui/src/lib/format.ts`, append at the end of the file:

```ts
const SIGNED_USD_FMT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "+$84.20" / "-$210.80" / "$0.00" — a P/L dollar amount with an explicit
 *  leading sign for non-zero values, so a gain reads unambiguously on the
 *  arena leaderboard. */
export function formatSignedUsd(n: number): string {
  const body = SIGNED_USD_FMT.format(Math.abs(n));
  if (n > 0) return `+${body}`;
  if (n < 0) return `-${body}`;
  return body;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && npm run test -- src/lib/format.test.ts`
Expected: PASS (all existing + 3 new).

- [ ] **Step 5: Commit**

```bash
cd ui
git add src/lib/format.ts src/lib/format.test.ts
git commit -m "feat(ui): add formatSignedUsd for signed P/L dollars"
```

---

### Task 3: Parameterize `useBotStatus` by agent (`botStatus.ts`)

**Files:**
- Modify: `ui/src/api/botStatus.ts` (`useBotStatus` is at lines 64-79)
- Test: `ui/src/api/botStatus.test.ts`

**Interfaces:**
- Produces:
  - `function botStatusUrl(agentId?: string): string` — `"/bot-status.json"` when no id, `"/bot-status-<id>.json"` when given.
  - `useBotStatus(agentId?: string)` — fetches `botStatusUrl(agentId)`; query key keyed by id so each agent caches separately. Back-compatible: `useBotStatus()` behaves exactly as before.

- [ ] **Step 1: Write the failing test**

Create `ui/src/api/botStatus.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { botStatusUrl } from "./botStatus";

describe("botStatusUrl", () => {
  it("returns the legacy single-bot path with no agentId", () => {
    expect(botStatusUrl()).toBe("/bot-status.json");
  });

  it("returns the per-agent path for an arena agentId", () => {
    expect(botStatusUrl("bold")).toBe("/bot-status-bold.json");
    expect(botStatusUrl("contrarian")).toBe("/bot-status-contrarian.json");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npm run test -- src/api/botStatus.test.ts`
Expected: FAIL — `botStatusUrl` is not exported.

- [ ] **Step 3: Write the implementation**

In `ui/src/api/botStatus.ts`, replace the existing `useBotStatus` function (lines 64-79) with:

```ts
/** Static path for an agent's status file. The arena writes one per agent
 *  (`bot-status-<id>.json`); the legacy single bot uses `bot-status.json`. */
export function botStatusUrl(agentId?: string): string {
  return agentId ? `/bot-status-${agentId}.json` : "/bot-status.json";
}

export function useBotStatus(agentId?: string) {
  return useQuery({
    queryKey: ["bot-status", agentId ?? "default"],
    queryFn: async (): Promise<BotStatus> => {
      // Cache-bust so the static asset never serves a stale cycle.
      const res = await fetch(`${botStatusUrl(agentId)}?t=${Date.now()}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`bot-status ${res.status}`);
      return (await res.json()) as BotStatus;
    },
    refetchInterval: 4_000,
    staleTime: 2_000,
    retry: false,
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && npm run test -- src/api/botStatus.test.ts`
Expected: PASS (3 assertions across 2 tests).

- [ ] **Step 5: Typecheck (confirms the existing `useBotStatus()` caller still type-checks)**

Run: `cd ui && npm run typecheck`
Expected: no errors (`AgentPage` still calls `useBotStatus()` with no args — valid).

- [ ] **Step 6: Commit**

```bash
cd ui
git add src/api/botStatus.ts src/api/botStatus.test.ts
git commit -m "feat(ui): parameterize useBotStatus by agentId via botStatusUrl"
```

---

### Task 4: Parameterize AgentPage for per-agent drill-down + routes

**Files:**
- Create: `ui/src/lib/useNowSeconds.ts`
- Modify: `ui/src/pages/AgentPage.tsx`
- Modify: `ui/src/App.tsx`

**Interfaces:**
- Consumes: `resolveAgentIdentity`, `useLeaderboard`, `AgentIdentity` (Task 1); `useBotStatus(agentId)` (Task 3); `useParams` from `react-router-dom`.
- Produces: `function useNowSeconds(): number` from `@/lib/useNowSeconds`; a `/agents/:agentId` route rendering `AgentPage` keyed by the param.

**Context for the implementer:** `AgentPage.tsx` currently (a) defines `useNowSeconds` locally at lines 27-38, (b) calls `useBotStatus()` and `usePositions(BOT_ADDRESS)`, (c) renders a `HeroBanner` that hard-codes the 🤖 emoji, `agentpit-trader` name, `shortAddr(BOT_ADDRESS)`, and `autonomous trading agent` tagline. We extract the clock hook, then feed the hero a resolved `AgentIdentity` so the same component renders either the legacy single bot (no param) or any arena agent (`:agentId`). Positions come from the resolved agent's `address`.

- [ ] **Step 1: Extract the shared clock hook**

Create `ui/src/lib/useNowSeconds.ts`:

```ts
import { useEffect, useState } from "react";

/** A 1 Hz ticking clock (unix seconds) so countdowns and "live" judgements
 *  re-render each second. Shared by the agent detail + arena hub pages. */
export function useNowSeconds(): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const id = window.setInterval(
      () => setNow(Math.floor(Date.now() / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);
  return now;
}
```

- [ ] **Step 2: Rewire AgentPage imports + remove the local hook**

In `ui/src/pages/AgentPage.tsx`, replace the top import block (lines 1-15) with:

```tsx
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowDownRight, ArrowUpRight, Minus, Play } from "lucide-react";
import type { Position } from "@/api/portfolio";
import { usePositions } from "@/api/portfolio";
import { useBotStatus, type BotFeedItem, type BotStatus } from "@/api/botStatus";
import {
  resolveAgentIdentity,
  useLeaderboard,
  type AgentIdentity,
} from "@/api/leaderboard";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { Sparkline } from "@/components/Sparkline";
import type { SparklineSample } from "@/lib/chartGeometry";
import { formatClock, formatCountdown } from "@/lib/format";
import { cn } from "@/lib/utils";
```

Then delete the now-duplicate local `useNowSeconds` definition (the block starting `/** A 1Hz ticking clock …` through its closing `}` — originally lines 27-38).

- [ ] **Step 3: Resolve identity + per-agent data in the component**

In `ui/src/pages/AgentPage.tsx`, replace the start of the `AgentPage` component — from `export function AgentPage() {` down to and including the `const open = useMemo(...)` block (originally lines 57-68) — with:

```tsx
export function AgentPage() {
  const now = useNowSeconds();
  const { agentId } = useParams();
  const { data: leaderboard } = useLeaderboard();
  const { identity, status: idStatus } = resolveAgentIdentity(
    leaderboard,
    agentId,
  );
  const { data: status, error: statusError } = useBotStatus(agentId);
  const { data: openData } = usePositions(identity?.address);

  const open = useMemo(
    () =>
      (openData ?? [])
        .filter((p) => p.size > 0)
        .sort((a, b) => b.currentValue - a.currentValue),
    [openData],
  );
```

- [ ] **Step 4: Add the not-found guard + pass identity to the hero**

In `ui/src/pages/AgentPage.tsx`, locate the `return (` of `AgentPage` (originally line 103). Immediately **before** it, insert the not-found guard (this sits after every hook + `useMemo`, so hook order is preserved):

```tsx
  if (idStatus === "not-found") {
    return (
      <section className="mx-auto max-w-5xl py-16 text-center">
        <p className="text-sm text-muted-foreground">
          No agent “{agentId}” in the arena.
        </p>
        <Link
          to="/agents"
          className="mt-3 inline-block text-sm text-primary hover:underline"
        >
          ← Back to Agent Arena
        </Link>
      </section>
    );
  }
```

Then, in that same `return`, change the `<HeroBanner ... />` usage to pass `identity` instead of relying on the global constant — replace:

```tsx
      <HeroBanner
        status={status}
        isLive={isLive}
        secsToNext={secsToNext}
        hasError={Boolean(statusError) && !status}
      />
```

with:

```tsx
      <HeroBanner
        identity={identity}
        status={status}
        isLive={isLive}
        secsToNext={secsToNext}
        hasError={Boolean(statusError) && !status}
      />
```

- [ ] **Step 5: Make HeroBanner render the resolved identity**

In `ui/src/pages/AgentPage.tsx`, replace the entire `HeroBanner` function (originally lines 163-231) with the version below. Only the props type, the avatar glyph, the name/tagline/address lines, and the new "← Agent Arena" back-link change; the wrapper element with its `style` gradient and the right-hand `Heartbeat`/countdown/`RunNowButton` cluster are preserved verbatim.

```tsx
function HeroBanner({
  identity,
  status,
  isLive,
  secsToNext,
  hasError,
}: {
  identity: AgentIdentity | null;
  status: BotStatus | undefined;
  isLive: boolean;
  secsToNext: number | null;
  hasError: boolean;
}) {
  // identity is null only briefly while the leaderboard loads for an arena
  // agent — fall back to neutral placeholders so the hero never flashes empty.
  const emoji = identity?.emoji ?? "🤖";
  const name = identity?.name ?? "…";
  const style = identity?.style ?? "";
  const addr = identity ? shortAddr(identity.address) : "";

  return (
    <div
      className="relative overflow-hidden rounded-2xl border bg-card px-6 py-6 sm:px-8"
      style={{
        backgroundImage:
          "radial-gradient(120% 140% at 100% 0%, hsl(var(--primary) / 0.06), transparent 55%), linear-gradient(hsl(var(--border) / 0.5) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border) / 0.5) 1px, transparent 1px)",
        backgroundSize: "auto, 34px 34px, 34px 34px",
        backgroundPosition: "center, center, center",
      }}
    >
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className="grid size-12 shrink-0 place-items-center rounded-xl border bg-background/70 text-2xl shadow-sm">
            {emoji}
          </div>
          <div>
            {identity?.isArena ? (
              <Link
                to="/agents"
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                ← Agent Arena
              </Link>
            ) : null}
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{name}</h1>
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                paper · demo
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              {addr ? `${addr} · ${style}` : style}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 sm:gap-5">
          <Heartbeat live={isLive} />
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
              {hasError
                ? "Awaiting first cycle"
                : isLive
                  ? "Next cycle"
                  : "Last cycle"}
            </div>
            <div className="font-mono text-lg font-semibold tabular-nums">
              {hasError
                ? "—"
                : isLive && secsToNext !== null
                  ? secsToNext > 0
                    ? `in ${formatCountdown(secsToNext)}`
                    : "running…"
                  : status
                    ? (formatClock(status.updated_at) ?? "—")
                    : "—"}
            </div>
          </div>
          <RunNowButton />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Add the routes**

In `ui/src/App.tsx`, add the `/agents/:agentId` route directly after the existing `/agent` route (line 22). Insert:

```tsx
            <Route path="/agents/:agentId" element={<AgentPage />} />
```

(Leave the existing `<Route path="/agent" element={<AgentPage />} />` as-is for now — Task 5 converts it to a redirect. `/agent` with no param resolves to `DEFAULT_IDENTITY`, so it keeps working in the meantime.)

- [ ] **Step 7: Verify — full suite, typecheck, lint, build**

Run: `cd ui && npm run test && npm run typecheck && npm run lint && npm run build`
Expected: all pass. (No new unit test in this task — the extracted logic it relies on is already tested in Tasks 1 & 3; this task's gate is a green suite + clean typecheck/lint/build. Then manually confirm at `http://localhost:5173/agents/bold` that the detail page renders the Bold hero — emoji 🔥, name "Bold", its address — and that `/agent` still renders the legacy 🤖 hero.)

- [ ] **Step 8: Commit**

```bash
cd ui
git add src/lib/useNowSeconds.ts src/pages/AgentPage.tsx src/App.tsx
git commit -m "feat(ui): parameterize AgentPage by agentId for arena drill-down"
```

---

### Task 5: Agent Arena hub page (`/agents`) + nav + legacy redirect

**Files:**
- Create: `ui/src/pages/AgentArenaPage.tsx`
- Modify: `ui/src/App.tsx`
- Modify: `ui/src/components/TopNav.tsx`

**Interfaces:**
- Consumes: `useLeaderboard`, `rankAgents`, `equityPoints`, `RankedAgent` (Task 1); `formatSignedUsd`, `formatCountdown` (Task 2 + existing); `useNowSeconds` (Task 4); `Sparkline` (existing).
- Produces: `function AgentArenaPage()`; the `/agents` route; nav pill pointing at `/agents`.

- [ ] **Step 1: Build the hub page**

Create `ui/src/pages/AgentArenaPage.tsx`:

```tsx
import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import {
  equityPoints,
  rankAgents,
  useLeaderboard,
  type RankedAgent,
} from "@/api/leaderboard";
import { useNowSeconds } from "@/lib/useNowSeconds";
import { formatCountdown, formatSignedUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

const pnlText = (n: number) =>
  n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : n < 0
      ? "text-rose-600 dark:text-rose-400"
      : "text-muted-foreground";

const pnlTone = (n: number): "up" | "down" | "neutral" =>
  n > 0 ? "up" : n < 0 ? "down" : "neutral";

export function AgentArenaPage() {
  const now = useNowSeconds();
  const { data, error } = useLeaderboard();
  const agents = data ? rankAgents(data.agents) : [];

  const interval = (data?.cycle_interval_minutes ?? 15) * 60;
  const sinceUpdate = data ? now - data.updated_at : Infinity;
  const secsToNext = data ? data.updated_at + interval - now : null;
  // "Live" while the last cycle is within two intervals; otherwise the cron is
  // paused/stalled and we show an honest idle state.
  const isLive = sinceUpdate < interval * 2 + 60;

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <span aria-hidden>🏆</span> Agent Arena
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Five personalities trading the same news signals — ranked by live
            Total P&amp;L.
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            {data ? `${data.agents.length} agents` : "—"}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="tabular-nums text-muted-foreground">
            {isLive && secsToNext !== null
              ? secsToNext > 0
                ? `next cycle in ${formatCountdown(secsToNext)}`
                : "running…"
              : "idle"}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold",
              isLive
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
            )}
          >
            <span
              className={cn(
                "inline-flex size-1.5 rounded-full",
                isLive ? "animate-pulse bg-emerald-500" : "bg-amber-500",
              )}
            />
            {isLive ? "live" : "paused"}
          </span>
        </div>
      </header>

      {error && !data ? (
        <div className="rounded-2xl border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
          The leaderboard isn't available yet — it appears after the first cycle.
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border bg-card">
          <div className="hidden grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem] items-center gap-3 border-b px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground sm:grid">
            <span>#</span>
            <span>Agent</span>
            <span className="text-right">Total P&amp;L</span>
            <span className="text-center">Equity</span>
            <span className="text-right">Trades</span>
          </div>
          <ul className="divide-y">
            {agents.length === 0 ? (
              <li className="grid place-items-center px-4 py-12 text-center text-sm text-muted-foreground">
                Loading agents…
              </li>
            ) : (
              agents.map((a) => <AgentRow key={a.id} agent={a} />)
            )}
          </ul>
        </div>
      )}
    </section>
  );
}

function AgentRow({ agent }: { agent: RankedAgent }) {
  return (
    <li>
      <Link
        to={`/agents/${agent.id}`}
        className="grid grid-cols-[3rem_minmax(0,1fr)_8rem] items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50 sm:grid-cols-[3rem_minmax(0,1fr)_8rem_7rem_4rem]"
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
```

- [ ] **Step 2: Wire the route + redirect the legacy path**

In `ui/src/App.tsx`:

1. Add the import alongside the other page imports (after the `AgentPage` import on line 5):

```tsx
import { AgentArenaPage } from "@/pages/AgentArenaPage";
```

2. Replace the legacy `/agent` route line (`<Route path="/agent" element={<AgentPage />} />`) with the hub route, the redirect, and keep the detail route from Task 4. The agent routes block should read:

```tsx
            <Route path="/agents" element={<AgentArenaPage />} />
            <Route path="/agents/:agentId" element={<AgentPage />} />
            <Route path="/agent" element={<Navigate to="/agents" replace />} />
```

(`Navigate` is already imported on line 1 of `App.tsx`.)

- [ ] **Step 3: Point the nav pill at the arena**

In `ui/src/components/TopNav.tsx`, the live nav pill (lines 100-112) links to `/agent` with the label "Agent Live". Change the `to` and the label. Replace:

```tsx
        <NavLink
          to="/agent"
```

with:

```tsx
        <NavLink
          to="/agents"
```

and replace the label text on the line that reads `          Agent Live` with:

```tsx
          Arena
```

(Leave the pulse dot and the active/inactive className logic unchanged — `NavLink to="/agents"` is active on both `/agents` and `/agents/:id`.)

- [ ] **Step 4: Verify — full suite, typecheck, lint, build**

Run: `cd ui && npm run test && npm run typecheck && npm run lint && npm run build`
Expected: all pass. Then manually verify with the dev server (`npm run dev`):
  - `http://localhost:5173/agents` lists all five agents (🔥 Bold, 🛡️ Cautious, 🔀 Contrarian, 🎰 Longshot, 🔗 Hybrid), each with a Total P&L, equity sparkline, and trade count; rows ordered by Total P&L; medals on the top three.
  - Clicking a row navigates to `/agents/<id>` and shows that agent's detail hero + positions + feed.
  - The TopNav "Arena" pill highlights on both `/agents` and `/agents/<id>`.
  - Visiting `/agent` redirects to `/agents`.

- [ ] **Step 5: Commit**

```bash
cd ui
git add src/pages/AgentArenaPage.tsx src/App.tsx src/components/TopNav.tsx
git commit -m "feat(ui): Agent Arena leaderboard hub at /agents with drill-down"
```

---

## Post-Implementation: visual polish (separate, optional)

After the five tasks land and verify, the hub + detail are functional but plain. A follow-up pass with the **frontend-design** skill can elevate the arena's visual identity (typography, podium treatment for the top three, motion on rank changes, richer equity sparklines). Keep it a separate change so the functional leaderboard is reviewable on its own. Do not block this plan's completion on it.

---

## Self-Review

**1. Spec coverage** (`2026-06-30-agent-arena-leaderboard-design.md`):
- "New hub page `/agents`" → Task 5. ✓
- "ranked by P&L … Total P&L = realized + unrealized … sort descending; medals 🥇🥈🥉 top 3" → `rankAgents` (Task 1) + row render (Task 5). ✓
- "Each row: rank (medal) · emoji + name · style one-liner · Total P&L (live, colored) · equity-curve sparkline · trade count" → `AgentRow` (Task 5). ✓
- "Live: recomputed every cycle, ranks visibly move" → `useLeaderboard` 4 s poll + `useNowSeconds` countdown (Tasks 1, 4, 5). ✓
- "Clicking a row drills into the existing AgentPage detail view, parameterized by agent" → Task 4 (`/agents/:agentId`, `resolveAgentIdentity`, per-agent `useBotStatus`/positions). ✓
- "each writes `bot-status-<id>.json` (today's format) so the existing AgentPage can render any agent by id" → `botStatusUrl`/`useBotStatus(agentId)` (Task 3). ✓
- "a small `leaderboard.json` aggregates the 5 … the new `/agents` page reads it" → `useLeaderboard` (Task 1). ✓
- Open question "`/agent` redirects or both coexist" → resolved: `/agent` → `/agents` redirect (Task 5, Global Constraints). ✓
- Open question "sparkline window 7d vs inception" → UI renders the bot-provided `equity` as-is; window owned by the bot (Global Constraints). ✓
- Out-of-scope items (maker execution, new strategies, backtest, redesign of detail view) → none added. ✓

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N"/bare prose-without-code steps. Every code step carries complete code. ✓

**3. Type consistency:** `LeaderboardAgent`/`LeaderboardData`/`RankedAgent`/`AgentIdentity`/`IdentityStatus` defined in Task 1 and consumed with matching names/shapes in Tasks 4 & 5. `equity: PnlPoint[]` matches `equityPoints(equity: PnlPoint[])` and the `leaderboard.json` sample's `equity: [{t,p}]`. `botStatusUrl`/`useBotStatus(agentId?)` (Task 3) match the call `useBotStatus(agentId)` (Task 4). `formatSignedUsd`/`formatCountdown` (Task 2/existing) match their hub call sites (Task 5). `useNowSeconds` from `@/lib/useNowSeconds` (Task 4) imported identically in Tasks 4 & 5. ✓
