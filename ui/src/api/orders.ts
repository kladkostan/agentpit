import { apiFetch } from "@/api/client";
import type { OrderResponse, PlaceOrderRequest } from "@/types/order";

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
