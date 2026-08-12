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
 * Close a series at `now`, anchored to `currentPrice` when it is known.
 *
 * `/prices-history` returns one point per trade, and a price holds until the
 * next one — an outcome that traded once at 14% is still 14% today. Without
 * the closing point a one-trade market has a single coordinate, and a path
 * with one coordinate is a lone `M x y`: a move with nothing to draw, so the
 * line is simply absent while the legend still lists the outcome at 14%.
 *
 * `currentPrice` is the price the headline shows — book-derived, not
 * trade-derived. The two sources can disagree without limit: a market whose
 * book collapses after its last print keeps holding that print forever, and
 * carrying it to `now` drew a flat line asserting a price that no longer
 * exists. A Counter-Strike market read "<1% chance" beside a chart ending at
 * 71% because the tape had stalled at 71¢ while the book fell to 0.1¢. Closing
 * on the live price instead makes the number and the line agree by
 * construction, whatever the tape is doing. Pass `undefined` when no live
 * price is known and the last trade is carried, as before.
 *
 * Markets that never traded are left empty: there is no history to close, and
 * inventing a flat line at today's price would draw a month that never
 * happened.
 */
export function carryPriceForward(
  points: ReadonlyArray<SparklineSample>,
  now: number,
  currentPrice?: number,
): ReadonlyArray<SparklineSample> {
  const last = points[points.length - 1];
  if (!last || last.t >= now) return points;
  // 0 is a real price (a resolved-against outcome), so test finiteness rather
  // than truthiness — `currentPrice || last.p` would silently discard it.
  const close =
    currentPrice !== undefined && Number.isFinite(currentPrice)
      ? currentPrice
      : last.p;
  return [...points, { t: now, p: close }];
}
