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
