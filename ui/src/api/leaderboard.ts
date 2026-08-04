import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { BOT_ADDRESS, type BotFeedItem, type PnlPoint } from "@/api/botStatus";
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

/** Newest feed item matching `matches`, or null. Does not trust feed order:
 *  picks the max (ts, decision_id) among matching items. */
function newestFeedItem(
  feed: BotFeedItem[],
  matches: (item: BotFeedItem) => boolean,
): BotFeedItem | null {
  let best: BotFeedItem | null = null;
  for (const item of feed) {
    if (!matches(item)) continue;
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

/** Newest feed item that actually traded, or null. */
export function lastTrade(feed: BotFeedItem[]): BotFeedItem | null {
  return newestFeedItem(feed, (item) => item.traded);
}

/** Newest feed item the agent chose NOT to trade (held/gated), or null. */
export function lastHold(feed: BotFeedItem[]): BotFeedItem | null {
  return newestFeedItem(feed, (item) => !item.traded);
}

/** Fetch the five house personalities' feed off the UI origin's static
 *  `public/leaderboard.json` — id/emoji/style/equity detail the real
 *  `/leaderboard` API doesn't carry. Powers the per-agent detail page
 *  (`AgentPage`) only; the ranked board itself now reads `useLeaderboard`
 *  below. Cache-busted + polled every 4s so the detail page's numbers visibly
 *  move during the demo. */
export function useArenaAgentsFeed() {
  return useQuery({
    queryKey: ["arena-agents-feed"],
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
  const lastPoint = agent.equity[agent.equity.length - 1];
  const realizedNow = lastPoint ? lastPoint.p : 0;
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

/* --------------------------------------------------------- real board --- */

/** One row of `GET /leaderboard` — every account that has traded, not just
 *  the house personalities above. */
export interface BoardEntry {
  rank: number;
  name: string;
  address: string;
  capital: string;
  earned: string;
  returnPct: number;
  trades: number;
  isHouseAgent: boolean;
}

export interface BoardResponse {
  sort: string;
  entries: BoardEntry[];
}

export const LEADERBOARD_SORTS = [
  { key: "return", label: "Return" },
  { key: "earned", label: "Earned" },
  { key: "capital", label: "Capital" },
  { key: "trades", label: "Trades" },
] as const;

export type LeaderboardSortKey = (typeof LEADERBOARD_SORTS)[number]["key"];

const BOARD_USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Base-unit integer string (6 decimals) to dollars. */
export function formatBoardAmount(raw: string): string {
  return BOARD_USD.format(Number(raw) / 1e6);
}

export function useLeaderboard(sort: string) {
  return useQuery({
    queryKey: ["leaderboard", sort],
    queryFn: () =>
      apiFetch<BoardResponse>(`/leaderboard?sort=${encodeURIComponent(sort)}`),
    refetchInterval: 30_000,
  });
}
