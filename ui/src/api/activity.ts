import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

/** One entry of the Data-API activity feed (§8.10). */
export interface ActivityEntry {
  timestamp: number;
  conditionId: string;
  /** TRADE | SPLIT | MERGE | REDEEM */
  type: string;
  size: number;
  usdcSize: number;
  price: number;
  /** BUY | SELL, only meaningful when type is TRADE. */
  side: string;
  title: string;
  slug: string;
  icon: string;
  outcome: string;
}

export const ACTIVITY_PAGE_SIZE = 25;

export async function listActivity(
  userAddress: string,
  limit: number = ACTIVITY_PAGE_SIZE,
): Promise<ActivityEntry[]> {
  return apiFetch<ActivityEntry[]>(
    `/activity?user=${encodeURIComponent(userAddress)}&limit=${limit}`,
  );
}

/** Human label for one entry: what happened, and to which outcome.
 *
 *  The feed carries position changes the account did not necessarily initiate
 *  as trades — a split mints both outcomes, a redeem cashes a resolved one —
 *  so the verb comes from `type` first and only falls back to `side`.
 */
export function describeActivity(entry: ActivityEntry): string {
  switch (entry.type) {
    case "TRADE":
      return entry.side === "SELL" ? "Sold" : "Bought";
    case "SPLIT":
      return "Split";
    case "MERGE":
      return "Merged";
    case "REDEEM":
      return "Redeemed";
    default:
      return entry.type || "Activity";
  }
}

export function useActivity(userAddress: string | undefined) {
  return useQuery({
    queryKey: ["activity", userAddress],
    queryFn: () => {
      if (!userAddress) throw new Error("userAddress is required");
      return listActivity(userAddress);
    },
    enabled: Boolean(userAddress),
    staleTime: 10_000,
  });
}
