import type { Market, MarketState } from "@/types/market";

/** Dot + label colours per market state. Shared so the badge reads the same on
 *  a market card, an event card and the detail page. */
export const STATE_TONE: Record<MarketState, { dot: string; label: string }> = {
  DRAFT: { dot: "bg-amber-500", label: "text-amber-700 dark:text-amber-400" },
  ACTIVE: {
    dot: "bg-emerald-500",
    label: "text-emerald-700 dark:text-emerald-400",
  },
  CLOSED: { dot: "bg-slate-400", label: "text-slate-600 dark:text-slate-300" },
  RESOLVED: { dot: "bg-sky-500", label: "text-sky-700 dark:text-sky-400" },
  CANCELLED: { dot: "bg-rose-500", label: "text-rose-700 dark:text-rose-400" },
};

/** Liveliest first: an event is as live as its liveliest market. */
const STATE_PRECEDENCE: MarketState[] = [
  "ACTIVE",
  "DRAFT",
  "RESOLVED",
  "CANCELLED",
  "CLOSED",
];

/** One state for a multi-outcome event.
 *
 *  ACTIVE wins whenever any market is active, which is deliberately the same
 *  rule the grid's "Active" filter and the live counter use — an event the grid
 *  calls live must not wear a different badge. Empty input reads CLOSED: no
 *  tradeable market means nothing to trade. */
export function eventState(markets: Market[]): MarketState {
  for (const state of STATE_PRECEDENCE) {
    if (markets.some((m) => m.market_state === state)) return state;
  }
  return "CLOSED";
}
