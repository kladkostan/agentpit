import type { OrderbookEntry } from "@/types/order";

export const SLIPPAGE_CAP = 0.02;
export const MIN_PROB = 0.01;
export const MAX_PROB = 0.99;
export const SHARES_SCALE = 1_000_000;

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
