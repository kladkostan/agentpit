export type MarketState =
  | "DRAFT"
  | "ACTIVE"
  | "CLOSED"
  | "RESOLVED"
  | "CANCELLED";

export type Erc1155Token = readonly [tokenId: string, label: string];

export interface Market {
  market_id: number;
  question: string;
  slug: string;
  description: string;
  erc1155_tokens: Erc1155Token[];
  start_date: number | null;
  end_date: number | null;
  market_state: MarketState;
  resolved_outcome: number | null;
  polymarket_id: number | null;
  condition_id: string;
  event_id: number | null;
  outcome_label: string | null;
  icon_url: string | null;
  /** One probability in [0, 1] per outcome, index-aligned with
   *  `erc1155_tokens`. Empty when the payload carried no usable prices. */
  outcome_prices: number[];
  /** Best bid / ask for outcome[0] (YES) in [0, 1] — the server ships exactly
   *  one pair per market (Gamma parity). `null` means no resting order on that
   *  side; the wire sends 0.0 for that case and it must not reach the UI as a
   *  real 0¢ quote. */
  best_bid: number | null;
  best_ask: number | null;
}

export interface ListMarketsResponse {
  markets: Market[];
  total: number;
  limit: number;
  offset: number;
}

export interface SparklinePoint {
  /** Trade timestamp in unix seconds. */
  t: number;
  /** Probability in [0, 1]. */
  p: number;
}

export interface PricesHistoryResponse {
  history: SparklinePoint[];
}
