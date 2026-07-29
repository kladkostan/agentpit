import type { Market } from "@/types/market";

/**
 * Sort markets by descending YES mid price (cents in [0, 1]).
 * Markets with no known mid fall to the bottom in their original order so
 * outcomes never disappear from the list while their orderbook is loading.
 */
export function sortMarketsByYesMid(
  markets: readonly Market[],
  yesMidByMarketId: ReadonlyMap<number, number>,
): Market[] {
  return markets
    .map((m, index) => ({ market: m, index }))
    .sort((a, b) => {
      const midA = yesMidByMarketId.get(a.market.market_id);
      const midB = yesMidByMarketId.get(b.market.market_id);
      const hasA = midA !== undefined;
      const hasB = midB !== undefined;
      if (hasA && hasB) {
        if (midB !== midA) return midB - midA;
        return a.index - b.index;
      }
      if (hasA) return -1;
      if (hasB) return 1;
      return a.index - b.index;
    })
    .map(({ market }) => market);
}

/** YES price per market id, taken straight from the list payload
 *  (`outcome_prices[0]`). Markets with no usable price are absent from the
 *  map — which is exactly what `sortMarketsByYesMid` treats as unknown and
 *  sorts last. */
export function yesPriceMap(
  markets: readonly Market[],
): ReadonlyMap<number, number> {
  const out = new Map<number, number>();
  for (const m of markets) {
    const price = m.outcome_prices[0];
    if (typeof price === "number" && Number.isFinite(price)) {
      out.set(m.market_id, price);
    }
  }
  return out;
}

/** Cents to BUY each side. YES costs its own best ask. NO is acquired through
 *  the YES book — the payload carries one bid/ask pair, describing YES — so it
 *  costs 1 − the YES best bid. */
export function buyChipCents(market: Market): {
  yes: number | null;
  no: number | null;
} {
  return {
    yes: market.best_ask !== null ? market.best_ask * 100 : null,
    no: market.best_bid !== null ? (1 - market.best_bid) * 100 : null,
  };
}
