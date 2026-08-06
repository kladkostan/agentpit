import { sortMarketsByYesMid } from "@/lib/eventOutcomes";
import type { SparklineSample } from "@/lib/chartGeometry";
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
): ReadonlyArray<ChartSeries> {
  const ranked = sortMarketsByYesMid(markets, midByMarket);
  const top = ranked.slice(0, Math.min(n, palette.length));
  return top.map((market, i) => ({
    market,
    label: market.outcome_label ?? market.question,
    color: palette[i]!,
  }));
}

/**
 * Carry a series' last traded price forward to `now`.
 *
 * `/prices-history` returns one point per trade, and a price holds until the
 * next one — an outcome that traded once at 14% is still 14% today. Without
 * the closing point a one-trade market has a single coordinate, and a path
 * with one coordinate is a lone `M x y`: a move with nothing to draw, so the
 * line is simply absent while the legend still lists the outcome at 14%.
 *
 * Markets that never traded are left empty: there is no price to carry, and
 * inventing a flat line at today's mid would draw a month of history that
 * never happened.
 */
export function carryLastPriceForward(
  points: ReadonlyArray<SparklineSample>,
  now: number,
): ReadonlyArray<SparklineSample> {
  const last = points[points.length - 1];
  if (!last || last.t >= now) return points;
  return [...points, { t: now, p: last.p }];
}
