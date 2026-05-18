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
