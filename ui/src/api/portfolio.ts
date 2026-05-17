import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface PortfolioPosition {
  market_id: number;
  question: string;
  token_id: string;
  outcome_label: string;
  outcome_index: number;
  balance: number;
}

export interface PortfolioResponse {
  eth_address: string;
  usdc_balance: number;
  positions: PortfolioPosition[];
}

export async function getPortfolio(): Promise<PortfolioResponse> {
  return apiFetch<PortfolioResponse>("/portfolio");
}

export function usePortfolio(enabled = true) {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: getPortfolio,
    enabled,
    staleTime: 10_000,
  });
}
