import type { OrderbookEntry } from "@/types/order";

export const SLIPPAGE_CAP = 0.02;
export const MIN_PROB = 0.01;
export const MAX_PROB = 0.99;
export const SHARES_SCALE = 1_000_000;
/** Micro-USDC per price level: 0.1¢ = $0.001. The order book displays one row
 * per tick, and orders are placed on this grid, so distinct sub-cent prices
 * collapse into a single level instead of rendering as duplicate rows. */
export const PRICE_TICK = 1000;

/** A price-aggregated order book level. */
export interface OrderbookLevel {
  price: number; // micro-USDC, snapped to a multiple of PRICE_TICK
  size: number; // summed micro-shares resting at this level
}

/** Collapse individual resting orders into 0.1¢ price levels, summing size. */
export function aggregateLevels(entries: OrderbookEntry[]): OrderbookLevel[] {
  const acc = new Map<number, number>();
  for (const e of entries) {
    const price = Math.round(e.PRICE / PRICE_TICK) * PRICE_TICK;
    acc.set(price, (acc.get(price) ?? 0) + e.REMAINING_AMOUNT);
  }
  return [...acc.entries()].map(([price, size]) => ({ price, size }));
}

/** Lowest ask after 0.1¢ aggregation — the order book's top-of-book "best
 *  ask", i.e. the price you pay to BUY one share right now. Aggregating first
 *  means this matches the cent the order book renders (raw sub-tick prices are
 *  snapped to the same grid). Returns null for an empty side. */
export function bestAskMicro(asks: OrderbookEntry[]): number | null {
  if (asks.length === 0) return null;
  return Math.min(...aggregateLevels(asks).map((l) => l.price));
}

/** Highest bid after aggregation — the best bid, i.e. the price you receive to
 *  SELL one share right now. Returns null for an empty side. */
export function bestBidMicro(bids: OrderbookEntry[]): number | null {
  if (bids.length === 0) return null;
  return Math.max(...aggregateLevels(bids).map((l) => l.price));
}

/** NO buy price in micro-USDC: the NO book's own best ask, or — when the NO
 *  book is empty — the complement of the YES best bid (a NO ask is the mirror
 *  of a YES bid, so NO ask = $1 − YES bid). Returns null when neither is known. */
export function deriveNoAskMicro(
  noAsks: OrderbookEntry[],
  yesBids: OrderbookEntry[],
): number | null {
  const own = bestAskMicro(noAsks);
  if (own !== null) return own;
  const yesBid = bestBidMicro(yesBids);
  return yesBid !== null ? 1_000_000 - yesBid : null;
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
  priceCap: number;     // probability used for the wire price
  sizeWire: number;     // integer micro-shares for the wire size
  bestAsk: number;      // top-of-book ask for preview display
}

/**
 * Given asks (sorted or unsorted) and a dollar budget, derive the
 * (price, size) for a GTC limit that fills against the book up to the
 * slippage cap. The remainder, if any, can be DELETE'd by the caller.
 */
export function computeMarketBuy(
  asks: OrderbookEntry[],
  dollarAmount: number,
): MarketBuyComputation | null {
  if (asks.length === 0 || dollarAmount <= 0) return null;
  const best = Math.min(...asks.map((a) => a.PRICE)) / 1_000_000;
  const priceCap = Math.min(best + SLIPPAGE_CAP, MAX_PROB);
  const sizeWire = Math.floor((dollarAmount * SHARES_SCALE) / priceCap);
  if (sizeWire <= 0) return null;
  return { priceCap, sizeWire, bestAsk: best };
}

export interface MarketSellComputation {
  priceCap: number;
  sizeWire: number;
  bestBid: number;
}

export function computeMarketSell(
  bids: OrderbookEntry[],
  shares: number,
): MarketSellComputation | null {
  if (bids.length === 0 || shares <= 0) return null;
  const best = Math.max(...bids.map((b) => b.PRICE)) / 1_000_000;
  const priceCap = Math.max(best - SLIPPAGE_CAP, MIN_PROB);
  const sizeWire = Math.floor(shares * SHARES_SCALE);
  if (sizeWire <= 0) return null;
  return { priceCap, sizeWire, bestBid: best };
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
