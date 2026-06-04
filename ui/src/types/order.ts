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

export interface OrderBookLevel {
  price: string; // decimal 0–1
  size: string;  // decimal shares
}

export interface OrderBookSummary {
  market: string;       // condition_id
  asset_id: string;     // token_id
  timestamp: string;
  hash: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  min_order_size: string;
  tick_size: string;
  neg_risk: boolean;
  last_trade_price: string;
}

export interface MarketOrderResult {
  filledShares: number;       // display shares (decimal, from postOrder amounts)
  remainingShares: number;
  avgPrice: number | null;
  txHash: string | null;
  cancelledRemainder: boolean;
  cancelError?: string;
  orderID: string;
}
