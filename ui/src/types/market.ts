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
  /** Price in micro-USDC (divide by 1e6 to get dollars in [0, 1]). */
  p: number;
}

export interface SparklineResponse {
  market_id: number;
  outcome: string;
  window_hours: number;
  points: SparklinePoint[];
  /** Window volume in micro-USDC (divide by 1e6 for dollars). */
  volume_micro_usd: number;
}
