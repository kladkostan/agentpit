import { useQuery } from "@tanstack/react-query";
import { ApiError, apiFetch } from "@/api/client";
import { SHARES_SCALE, computeMarketBuy, computeMarketSell } from "@/components/orders/orderMath";
import type {
  MarketOrderResult,
  OrderSide,
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

export interface PlaceMarketOrderArgs {
  marketId: number;
  outcome: string;
  side: OrderSide;
  /** For BUY: dollar amount. For SELL: display-share count. */
  amount: number;
  book: OrderbookResponse;
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

  const response = await placeOrder({
    market_id: args.marketId,
    outcome: args.outcome,
    side: args.side,
    price: computation.priceCap,
    size: computation.sizeWire,
    order_type: "GTC",
  });

  let cancelledRemainder = false;
  let cancelError: string | undefined;
  if (
    response.success &&
    Number(response.remainingSize) > 0 &&
    response.status === "live"
  ) {
    try {
      await cancelOrder(response.orderID);
      cancelledRemainder = true;
    } catch (err) {
      cancelError = err instanceof ApiError ? err.message : String(err);
    }
  }

  const filledShares = Number(response.filledSize) / SHARES_SCALE;
  const remainingShares = Number(response.remainingSize) / SHARES_SCALE;
  const result: MarketOrderResult = {
    filledShares,
    remainingShares,
    avgPrice: response.avgPrice ? Number(response.avgPrice) : null,
    txHash: response.txHash ?? null,
    cancelledRemainder,
    orderID: response.orderID,
  };
  if (cancelError !== undefined) {
    result.cancelError = cancelError;
  }
  return result;
}
