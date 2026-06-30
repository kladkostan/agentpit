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
