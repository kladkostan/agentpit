import { useQuery } from "@tanstack/react-query";

/**
 * The agentpit-trader paper bot publishes a small `status.json` into the web
 * app's `public/` each cycle (its reasoning lives in a local ledger, not in the
 * agentpit backend — this is the same-origin bridge that surfaces it). Served as
 * a static asset, so we fetch it directly off the UI origin, NOT through the
 * `apiFetch` client that targets the :8000 API.
 */

export interface BotFeedItem {
  ts: number;
  cycle_id: string;
  decision_id: string;
  title: string;
  direction: "UP" | "DOWN" | "NONE";
  recent_move: number; // signed price delta vs last cycle (dollars, e.g. 0.03 = +3¢)
  rationale: string;
  edge_source: string;
  outcome: string; // traded | demo_override | no_trade
  traded: boolean;
  demo: boolean;
  side: string; // BUY | SELL
  price: number | null;
  size: number | null;
  sources?: { title: string; url: string; source: string }[]; // news the model read
  hold_reason?: string; // why the preset held (arena gated decision); "" / absent otherwise
}

export interface BotSummary {
  closed_trades: number;
  realized_pnl: number;
  wins: number;
  losses: number;
  hit_rate: number;
  avg_win: number;
  avg_loss: number;
  open_positions: number;
  open_exposure_usd: number;
}

export interface PnlPoint {
  t: number; // unix seconds (0 = baseline)
  p: number; // cumulative realized P/L in USD
}

export interface BotStatus {
  updated_at: number; // unix seconds
  cycle_interval_minutes: number;
  demo_mode: boolean;
  summary: BotSummary;
  pnl_series: PnlPoint[];
  feed: BotFeedItem[];
}

/** Fixed paper-bot account (public reads only). Override via VITE_BOT_ADDRESS.
 * news-first bot's own account (separate from the retired demo bot), so the
 * positions panel shows only news-first's holdings. */
export const BOT_ADDRESS =
  (typeof import.meta.env.VITE_BOT_ADDRESS === "string" &&
  import.meta.env.VITE_BOT_ADDRESS.length > 0
    ? import.meta.env.VITE_BOT_ADDRESS
    : "0x5b3DfFE03Dbf0CB0793C62fff3e4e42204F927AD");

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
