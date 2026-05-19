import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Market, SparklineResponse } from "@/types/market";

export async function getMarket(id: number | string): Promise<Market> {
  return apiFetch<Market>(`/markets/${id}`);
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

export async function getSparkline(
  marketId: number,
  outcome: string,
): Promise<SparklineResponse> {
  return apiFetch<SparklineResponse>(
    `/sparkline/${marketId}/${encodeURIComponent(outcome)}`,
  );
}

export function useSparkline(
  marketId: number,
  outcome: string | undefined,
) {
  return useQuery({
    queryKey: ["sparkline", marketId, outcome],
    queryFn: () => {
      if (!outcome) throw new Error("outcome is required");
      return getSparkline(marketId, outcome);
    },
    enabled: Boolean(outcome),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
  });
}
