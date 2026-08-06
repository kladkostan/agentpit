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
  /** Slug of the event grouping this market; "" when it belongs to none. */
  eventSlug: string;
  icon: string;
  outcome: string;
}

/** Where a row's title should link.
 *
 *  The event page is the destination: a market is one outcome inside a
 *  question, and landing on the bare market hides the siblings the user was
 *  choosing between. Markets with no event fall back to their own page rather
 *  than to a broken `/events/` URL.
 */
export function marketHref(entry: {
  eventSlug?: string | undefined;
  slug: string;
}): string {
  const event = entry.eventSlug?.trim();
  if (event) return `/events/${event}`;
  return `/markets/${entry.slug}`;
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
