import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  OrderbookResponse,
  OrderResponse,
  PlaceOrderRequest,
} from "@/types/order";

export async function placeOrder(
  req: PlaceOrderRequest,
): Promise<OrderResponse> {
  return apiFetch<OrderResponse>("/orders", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function cancelOrder(orderId: string): Promise<void> {
  await apiFetch<{ order_id: string; status: string }>(
    `/orders/${encodeURIComponent(orderId)}`,
    { method: "DELETE" },
  );
}

export async function getOrderbook(
  marketId: number,
  outcome: string,
): Promise<OrderbookResponse> {
  return apiFetch<OrderbookResponse>(
    `/orderbook/${marketId}/${encodeURIComponent(outcome)}`,
  );
}

export function useOrderbook(
  marketId: number | undefined,
  outcome: string | undefined,
) {
  return useQuery({
    queryKey: ["orderbook", marketId, outcome],
    queryFn: () => {
      if (marketId === undefined || !outcome) {
        throw new Error("marketId and outcome are required");
      }
      return getOrderbook(marketId, outcome);
    },
    enabled: marketId !== undefined && Boolean(outcome),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}
