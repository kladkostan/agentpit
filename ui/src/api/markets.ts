import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { Market } from "@/types/market";

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
