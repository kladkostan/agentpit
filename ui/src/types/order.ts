export type OrderSide = "BUY" | "SELL";
export type OrderType = "GTC" | "FOK" | "FAK" | "GTD";

export interface PlaceOrderRequest {
  market_id: number;
  outcome: string;       // label, e.g. "Yes" / "No"
  side: OrderSide;
  price: number;         // 0 < price < 1
  size: number;          // integer micro-shares (display × 1e6)
  order_type?: OrderType;
  expiration?: number;
}

export interface OrderResponse {
  success: boolean;
  orderID: string;
  status: string;        // "live" | "matched" | "cancelled" | "failed"
  filledSize: string;    // micro-shares as decimal string
  remainingSize: string; // micro-shares as decimal string
  avgPrice?: string | null;
  errorMsg?: string | null;
  txHash?: string | null;
}

export interface OrderbookEntry {
  ORDER_ID: string;
  SIDE: OrderSide;
  PRICE: number;             // integer micro-USDC
  REMAINING_AMOUNT: number;  // integer micro-shares
  MAKER: string;
  CREATED_AT: number;
}

export interface OrderbookResponse {
  market_id: number;
  outcome: string;
  bids: OrderbookEntry[];
  asks: OrderbookEntry[];
}

export interface MarketOrderResult {
  filledShares: number;       // display shares (already divided by 1e6)
  remainingShares: number;
  avgPrice: number | null;
  txHash: string | null;
  cancelledRemainder: boolean;
  cancelError?: string;
  orderID: string;
}
