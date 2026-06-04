import { useQuery } from "@tanstack/react-query";
import { ApiError, apiFetch } from "@/api/client";
import { computeMarketBuy, computeMarketSell } from "@/components/orders/orderMath";
import type {
  MarketOrderResult,
  OrderBookSummary,
  OrderSide,
  OrderResponse,
  PlaceOrderRequest,
} from "@/types/order";

export async function placeOrder(
  req: PlaceOrderRequest,
): Promise<OrderResponse> {
  return apiFetch<OrderResponse>("/order", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function cancelOrder(orderId: string): Promise<void> {
  // DELETE /order takes the id in the body; response is {canceled, not_canceled}.
  await apiFetch<{ canceled: string[]; not_canceled: Record<string, string> }>(
    "/order",
    { method: "DELETE", body: JSON.stringify({ orderID: orderId }) },
  );
}

export async function getBook(tokenId: string): Promise<OrderBookSummary> {
  return apiFetch<OrderBookSummary>(`/book?token_id=${encodeURIComponent(tokenId)}`);
}

export function useBook(tokenId: string | undefined) {
  return useQuery({
    queryKey: ["book", tokenId],
    queryFn: () => {
      if (!tokenId) throw new Error("tokenId is required");
      return getBook(tokenId);
    },
    enabled: Boolean(tokenId),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}

export interface PlaceMarketOrderArgs {
  tokenId: string;
  side: OrderSide;
  /** For BUY: dollar amount. For SELL: display-share count. */
  amount: number;
  book: OrderBookSummary;
}

export async function placeMarketOrder(
  args: PlaceMarketOrderArgs,
): Promise<MarketOrderResult> {
  const computation =
    args.side === "BUY"
      ? computeMarketBuy(args.book.asks, args.amount)
      : computeMarketSell(args.book.bids, args.amount);

  if (computation === null) {
    throw new Error(
      args.side === "BUY"
        ? "No asks available — use a limit order"
        : "No bids available — use a limit order",
    );
  }

  // computation.size is a display-share quantity (may be fractional); the
  // backend accepts fractional decimal sizes, like Polymarket.
  const requestedShares = computation.size;
  const response = await placeOrder({
    token_id: args.tokenId,
    side: args.side,
    price: computation.priceCap,
    size: requestedShares,
    order_type: "GTC",
  });

  // postOrder amounts are taker-perspective decimal strings ("" when unfilled):
  //   BUY  → makingAmount = USDC spent,  takingAmount = shares received
  //   SELL → makingAmount = shares given, takingAmount = USDC received
  const filledShares =
    args.side === "BUY"
      ? Number(response.takingAmount || "0")
      : Number(response.makingAmount || "0");
  const usd =
    args.side === "BUY"
      ? Number(response.makingAmount || "0")
      : Number(response.takingAmount || "0");
  const remainingShares = Math.max(0, requestedShares - filledShares);
  const avgPrice = filledShares > 0 ? usd / filledShares : null;

  // A market order that didn't fully fill leaves a resting remainder
  // (status "live"); cancel it so the order behaves IOC-style.
  let cancelledRemainder = false;
  let cancelError: string | undefined;
  if (response.success && response.status === "live") {
    try {
      await cancelOrder(response.orderID);
      cancelledRemainder = true;
    } catch (err) {
      cancelError = err instanceof ApiError ? err.message : String(err);
    }
  }

  const result: MarketOrderResult = {
    filledShares,
    remainingShares,
    avgPrice,
    txHash: response.transactionsHashes[0] ?? null,
    cancelledRemainder,
    orderID: response.orderID,
  };
  if (cancelError !== undefined) {
    result.cancelError = cancelError;
  }
  return result;
}
