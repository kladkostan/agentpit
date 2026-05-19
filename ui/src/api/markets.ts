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
  windowHours = 24,
): Promise<SparklineResponse> {
  const params = new URLSearchParams({ window_hours: String(windowHours) });
  return apiFetch<SparklineResponse>(
    `/sparkline/${marketId}/${encodeURIComponent(outcome)}?${params}`,
  );
}

export function useSparkline(
  marketId: number,
  outcome: string | undefined,
  windowHours = 24,
) {
  return useQuery({
    queryKey: ["sparkline", marketId, outcome, windowHours],
    queryFn: () => {
      if (!outcome) throw new Error("outcome is required");
      return getSparkline(marketId, outcome, windowHours);
    },
    enabled: Boolean(outcome),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
  });
}
