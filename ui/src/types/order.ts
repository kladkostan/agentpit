export type OrderSide = "BUY" | "SELL";
export type OrderType = "GTC" | "FOK" | "FAK" | "GTD";

export interface PlaceOrderRequest {
  token_id: string;
  side: OrderSide;
  price: number;         // 0 < price < 1
  size: number;          // whole shares (NOT micro)
  order_type?: OrderType;
  expiration?: number;
}

export interface OrderResponse {
  success: boolean;
  errorMsg: string;
  orderID: string;
  status: string;                 // "live" | "matched"
  transactionsHashes: string[];
  takingAmount: string;           // decimal string; "" when unfilled
  makingAmount: string;           // decimal string; "" when unfilled
  tradeIDs: string[];
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
