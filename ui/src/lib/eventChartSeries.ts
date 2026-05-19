import { sortMarketsByYesMid } from "@/lib/eventOutcomes";
import type { Market } from "@/types/market";

export interface ChartSeries {
  market: Market;
  label: string;
  color: string;
}

/**
 * Pick the top-N markets to render on the event chart, ordered by
 * descending current YES mid. Each picked market gets a palette color
 * assigned by rank — #1 → palette[0], #2 → palette[1], and so on. The
 * palette is never wrapped; if there are more markets than colors the
 * tail is dropped.
 */
export function pickChartSeries(
  markets: ReadonlyArray<Market>,
  midByMarket: ReadonlyMap<number, number>,
  palette: ReadonlyArray<string>,
  n: number,
): ChartSeries[] {
  const ranked = sortMarketsByYesMid(markets, midByMarket);
  const top = ranked.slice(0, Math.min(n, palette.length));
  return top.map((market, i) => ({
    market,
    label: market.outcome_label ?? market.question,
    color: palette[i]!,
  }));
}
