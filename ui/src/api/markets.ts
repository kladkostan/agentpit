import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ListMarketsResponse, Market } from "@/types/market";

export const MARKETS_PAGE_SIZE = 20;

export interface ListMarketsParams {
  limit: number;
  offset: number;
}

export async function listMarkets(
  params: ListMarketsParams,
): Promise<ListMarketsResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  return apiFetch<ListMarketsResponse>(`/markets?${search.toString()}`);
}

export async function getMarket(id: number | string): Promise<Market> {
  return apiFetch<Market>(`/markets/${id}`);
}

export function useMarketsInfinite() {
  return useInfiniteQuery({
    queryKey: ["markets", "infinite", MARKETS_PAGE_SIZE],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listMarkets({ limit: MARKETS_PAGE_SIZE, offset: pageParam }),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.markets.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });
}

export function useMarket(id: number | string | undefined) {
  return useQuery({
    queryKey: ["market", id],
    queryFn: () => {
      if (id === undefined) {
        throw new Error("Market id is required");
      }
      return getMarket(id);
    },
    enabled: id !== undefined,
  });
}
