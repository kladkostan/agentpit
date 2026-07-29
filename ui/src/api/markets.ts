import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GammaMarket } from "@/types/gamma";
import type { Market, MarketState, PricesHistoryResponse } from "@/types/market";
import { isoToUnix } from "@/api/gamma-utils";

// `closed` wins over `active`: upstream Gamma can report a resolved market as
// active AND closed, and every "live" surface in the UI (the resolved-event
// filter in listEvents, the Active quick filter, the "N live" counter) must
// agree on one definition — a closed market is never live.
const _stateOf = (g: GammaMarket): MarketState =>
  g.closed ? "CLOSED" : g.active ? "ACTIVE" : "DRAFT";

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
  // A market is reachable by integer id (the /markets/:id route) OR by slug
  // (positions carry only a slug, no integer id). The backend's
  // /markets/{market_id} route is integer-only — sending it a slug 422s — so
  // resolve non-numeric ids through the slug filter, which returns a list.
  const isNumericId = typeof id === "number" || /^\d+$/.test(id);
  if (isNumericId) {
    return gammaToMarket(await apiFetch<GammaMarket>(`/markets/${id}`));
  }
  const [match] = await apiFetch<GammaMarket[]>(
    `/markets?slug=${encodeURIComponent(id)}`,
  );
  if (!match) {
    throw new Error(`Market not found for slug "${id}"`);
  }
  return gammaToMarket(match);
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
