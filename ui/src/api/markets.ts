import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GammaMarket } from "@/types/gamma";
import type { Market, MarketState, PricesHistoryResponse } from "@/types/market";
import { isoToUnix } from "@/api/gamma-utils";

const _stateOf = (g: GammaMarket): MarketState =>
  g.active ? "ACTIVE" : g.closed ? "CLOSED" : "DRAFT";

/** Map a Gamma wire market into the UI's internal Market shape. */
export function gammaToMarket(g: GammaMarket): Market {
  const labels = JSON.parse(g.outcomes) as string[];
  const tokenIds = JSON.parse(g.clobTokenIds) as string[];
  return {
    market_id: Number(g.id),
    question: g.question,
    slug: g.slug,
    description: g.description,
    erc1155_tokens: tokenIds.map((t, i) => [t, labels[i] ?? ""] as const),
    start_date: isoToUnix(g.startDate),
    end_date: isoToUnix(g.endDate),
    market_state: _stateOf(g),
    resolved_outcome: null,
    polymarket_id: null,
    condition_id: g.conditionId,
    event_id: null,
    outcome_label: g.groupItemTitle ?? null,
    icon_url: g.icon,
  };
}

export async function getMarket(id: number | string): Promise<Market> {
  const g = await apiFetch<GammaMarket>(`/markets/${id}`);
  return gammaToMarket(g);
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

export async function getPricesHistory(
  tokenId: string,
  interval = "1d",
): Promise<PricesHistoryResponse> {
  return apiFetch<PricesHistoryResponse>(
    `/prices-history?market=${encodeURIComponent(tokenId)}&interval=${interval}`,
  );
}

export function usePricesHistory(tokenId: string | undefined, interval = "1d") {
  return useQuery({
    queryKey: ["prices-history", tokenId, interval],
    queryFn: () => {
      if (!tokenId) throw new Error("tokenId is required");
      return getPricesHistory(tokenId, interval);
    },
    enabled: Boolean(tokenId),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: false,
  });
}
