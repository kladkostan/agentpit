import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface Position {
  proxyWallet: string;
  asset: string;          // token_id
  conditionId: string;
  size: number;           // display shares
  avgPrice: number;
  curPrice: number;
  cashPnl: number;
  percentPnl: number;
  initialValue: number;   // cost basis (avg x size)
  currentValue: number;
  outcome: string;
  outcomeIndex: number;
  oppositeOutcome: string;
  oppositeAsset: string;
  title: string;
  slug: string;
  icon: string;
  redeemable: boolean;
  endDate: string;        // market end/resolution time, unix seconds (string)
}

export async function getPositions(userAddress: string): Promise<Position[]> {
  return apiFetch<Position[]>(`/positions?user=${encodeURIComponent(userAddress)}`);
}

export function usePositions(userAddress: string | undefined) {
  return useQuery({
    queryKey: ["positions", userAddress],
    queryFn: () => {
      if (!userAddress) throw new Error("userAddress is required");
      return getPositions(userAddress);
    },
    enabled: Boolean(userAddress),
    staleTime: 10_000,
  });
}

export async function getClosedPositions(
  userAddress: string,
): Promise<Position[]> {
  return apiFetch<Position[]>(
    `/closed-positions?user=${encodeURIComponent(userAddress)}`,
  );
}

export function useClosedPositions(userAddress: string | undefined) {
  return useQuery({
    queryKey: ["closed-positions", userAddress],
    queryFn: () => {
      if (!userAddress) throw new Error("userAddress is required");
      return getClosedPositions(userAddress);
    },
    enabled: Boolean(userAddress),
    staleTime: 10_000,
  });
}

export async function getUsdcBalance(): Promise<number> {
  const r = await apiFetch<{ balance: string }>("/balance-allowance?asset_type=COLLATERAL");
  return Number(r.balance) / 1_000_000;
}

export function useUsdcBalance(enabled = true) {
  return useQuery({
    queryKey: ["balance-allowance", "COLLATERAL"],
    queryFn: getUsdcBalance,
    enabled,
    staleTime: 10_000,
  });
}
