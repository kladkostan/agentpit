import type { OrderBookLevel } from "@/types/order";

export const SLIPPAGE_CAP = 0.02;
export const MIN_PROB = 0.01;
export const MAX_PROB = 0.99;

/** A parsed order book level — dollars (0–1) and display shares. */
export interface OrderbookLevel {
  price: number; // dollars in [0, 1]
  size: number;  // display shares
}

/** Parse decimal-string levels from the wire into numeric display units. */
export function levelsFrom(levels: OrderBookLevel[]): OrderbookLevel[] {
  return levels.map((l) => ({ price: parseFloat(l.price), size: parseFloat(l.size) }));
}

/** Lowest ask in dollars — top-of-book best ask (price to BUY one share now).
 *  Returns null for an empty side. */
export function bestAsk(asks: OrderBookLevel[]): number | null {
  if (asks.length === 0) return null;
  return Math.min(...asks.map((l) => parseFloat(l.price)));
}

/** Highest bid in dollars — best bid (price to SELL one share now).
 *  Returns null for an empty side. */
export function bestBid(bids: OrderBookLevel[]): number | null {
  if (bids.length === 0) return null;
  return Math.max(...bids.map((l) => parseFloat(l.price)));
}

/** NO buy price in dollars: the NO book's own best ask, or — when the NO
 *  book is empty — the complement of the YES best bid (NO ask = $1 − YES bid).
 *  Returns null when neither is known. */
export function deriveNoAsk(
  noAsks: OrderBookLevel[],
  yesBids: OrderBookLevel[],
): number | null {
  const own = bestAsk(noAsks);
  if (own !== null) return own;
  const yesBidPrice = bestBid(yesBids);
  return yesBidPrice !== null ? 1 - yesBidPrice : null;
}

/** Cumulative notional ($) per level, accumulated from the touch (the price
 *  nearest the spread) outward — this is the order book's TOTAL column, and
 *  matches Polymarket's semantics. `levels` is in DISPLAY order (top→bottom).
 *  For asks the touch is the LAST element (best/lowest ask sits next to the
 *  spread), so totals grow upward; for bids the touch is the FIRST element
 *  (best/highest bid), so totals grow downward. Returns totals aligned to
 *  `levels` (totals[i] is the running sum through level i from the touch). */
export function cumulativeTotals(
  levels: OrderbookLevel[],
  side: "ask" | "bid",
): number[] {
  const totals = new Array<number>(levels.length).fill(0);
  let run = 0;
  if (side === "ask") {
    for (let i = levels.length - 1; i >= 0; i--) {
      run += levels[i]!.price * levels[i]!.size;
      totals[i] = run;
    }
  } else {
    for (let i = 0; i < levels.length; i++) {
      run += levels[i]!.price * levels[i]!.size;
      totals[i] = run;
    }
  }
  return totals;
}

/** Display shares from dollar amount at a price. Returns 0 for invalid inputs. */
export function sharesFromDollars(amount: number, price: number): number {
  if (amount <= 0 || price <= 0) return 0;
  return amount / price;
}

/** Dollar cost of N display shares at a price. */
export function dollarsFromShares(shares: number, price: number): number {
  if (shares <= 0 || price <= 0) return 0;
  return shares * price;
}

export interface MarketBuyComputation {
  priceCap: number; // probability used for the wire price
  size: number;     // whole shares for the order size
  bestAskPrice: number; // top-of-book ask for preview display
}

/**
 * Given asks (sorted or unsorted) and a dollar budget, derive the
 * (price, size) for a GTC limit that fills against the book up to the
 * slippage cap. The remainder, if any, can be DELETE'd by the caller.
 * Prices are already dollars in [0, 1]; returned size is whole shares.
 */
export function computeMarketBuy(
  asks: OrderBookLevel[],
  dollarAmount: number,
): MarketBuyComputation | null {
  if (asks.length === 0 || dollarAmount <= 0) return null;
  const best = Math.min(...asks.map((a) => parseFloat(a.price)));
  const priceCap = Math.min(best + SLIPPAGE_CAP, MAX_PROB);
  const size = dollarAmount / priceCap;
  if (size <= 0) return null;
  return { priceCap, size, bestAskPrice: best };
}

export interface MarketSellComputation {
  priceCap: number;
  size: number; // whole shares for the order size
  bestBidPrice: number;
}

export function computeMarketSell(
  bids: OrderBookLevel[],
  shares: number,
): MarketSellComputation | null {
  if (bids.length === 0 || shares <= 0) return null;
  const best = Math.max(...bids.map((b) => parseFloat(b.price)));
  const priceCap = Math.max(best - SLIPPAGE_CAP, MIN_PROB);
  const size = shares; // already whole shares
  if (size <= 0) return null;
  return { priceCap, size, bestBidPrice: best };
}

/** Pick the outcome a SELL action should target.
 *
 *  Default: keep what the user already selected. If they hold zero of it
 *  but more than zero of another outcome, switch to the held outcome so a
 *  click on SELL doesn't try to sell something they don't own.
 */
export function pickSellOutcome(
  currentOutcome: string,
  holdings: ReadonlyMap<string, number>,
): string {
  if ((holdings.get(currentOutcome) ?? 0) > 0) return currentOutcome;
  for (const [outcome, balance] of holdings) {
    if (balance > 0) return outcome;
  }
  return currentOutcome;
}
