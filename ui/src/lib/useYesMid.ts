import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { getBook } from "@/api/orders";
import type { Market } from "@/types/market";
import type { OrderBookSummary } from "@/types/order";

/**
 * Returns the mid-price (in dollars in [0, 1]) of the YES book for a market.
 * Falls back to whichever side exists if the book is single-sided.
 */
export function computeMid(book: OrderBookSummary | undefined): number | null {
  if (!book) return null;
  const bid =
    book.bids.length > 0
      ? Math.max(...book.bids.map((b) => parseFloat(b.price)))
      : null;
  const ask =
    book.asks.length > 0
      ? Math.min(...book.asks.map((a) => parseFloat(a.price)))
      : null;
  if (bid !== null && ask !== null) return (bid + ask) / 2;
  return ask ?? bid;
}

export function useOutcomeMid(tokenId: string | undefined) {
  const query = useQuery({
    queryKey: ["book", tokenId],
    queryFn: () => {
      if (!tokenId) throw new Error("tokenId is required");
      return getBook(tokenId);
    },
    enabled: Boolean(tokenId),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: 15_000,
  });
  return { ...query, mid: computeMid(query.data) };
}

/** Resolve a NO display price in cents.
 *
 *  When the NO book has resting orders, use its own mid — the YES and NO
 *  books trade independently off-chain, and surfacing the actual NO mid is
 *  what lets a trader spot a `p_YES + p_NO ≠ 1` arb. Only fall back to
 *  `100 − YES` when NO has no book yet.
 */
export function deriveNoCents(
  yesMid: number | null,
  noMid: number | null,
): number | null {
  if (noMid !== null) return noMid * 100;
  if (yesMid !== null) return 100 - yesMid * 100;
  return null;
}

/**
 * Fan-out variant for pages that need YES mids for many markets at once
 * (event detail, multi-market event cards). Returns a Map keyed by
 * `market_id` containing only the markets that have a known mid.
 *
 * Uses the same query key shape as `useOutcomeMid` so TanStack Query
 * dedupes requests across both hooks — a row using `useOutcomeMid` and a
 * parent using this hook share the cache for free.
 */
export function useYesMidMap(
  markets: readonly Market[],
): ReadonlyMap<number, number> {
  const queries = useQueries({
    queries: markets.map((m) => {
      const tokenId = m.erc1155_tokens[0]?.[0];
      return {
        queryKey: ["book", tokenId],
        queryFn: () => {
          if (!tokenId) throw new Error("tokenId is required");
          return getBook(tokenId);
        },
        enabled: Boolean(tokenId),
        refetchInterval: 30_000,
        refetchIntervalInBackground: false,
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      };
    }),
  });
  return useMemo(() => {
    const out = new Map<number, number>();
    queries.forEach((q, i) => {
      const mid = computeMid(q.data);
      if (mid !== null) out.set(markets[i]!.market_id, mid);
    });
    return out;
  }, [queries, markets]);
}
