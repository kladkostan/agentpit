import type { Market } from "@/types/market";

/**
 * Sort markets by descending YES mid price (cents in [0, 1]).
 * Markets with no known mid fall to the bottom in their original order so
 * outcomes never disappear from the list — no orderbook loads for this
 * anymore, but the price can still be absent (an empty `outcome_prices`).
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

/** Which market row an event page should open with, and on which outcome.
 *
 *  `wantedSlug` comes from the `?market=` the profile appends when it links a
 *  position at its event. Without it the page opens the top-ranked outcome,
 *  which for a rate decision is whichever is most likely — not the one the
 *  reader clicked. A stale or unknown slug falls back to the usual choice
 *  rather than selecting nothing.
 *
 *  `live` wins only when nothing was asked for: a rotating series should open
 *  its live window, but an explicit request still beats it.
 */
export function pickInitialSelection(
  ordered: ReadonlyArray<Market>,
  live: Market | null | undefined,
  wantedSlug: string | null,
  wantedOutcome: string | null,
): { marketId: number; outcome: string } | null {
  const requested = wantedSlug
    ? ordered.find((m) => m.slug === wantedSlug)
    : undefined;
  const market = requested ?? live ?? ordered[0];
  if (!market) return null;
  const labels = market.erc1155_tokens.map(([, label]) => label);
  const fallback = labels[0];
  if (fallback === undefined) return null;
  // Only honour the requested outcome on the requested market — carrying it
  // onto a fallback row would assert a side the reader never chose.
  const outcome =
    requested && wantedOutcome && labels.includes(wantedOutcome)
      ? wantedOutcome
      : fallback;
  return { marketId: market.market_id, outcome };
}
