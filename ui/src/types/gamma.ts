export interface GammaMarket {
  id: string;
  conditionId: string;
  question: string;
  slug: string;
  description: string;
  /** Short per-outcome name inside an event (e.g. "Spain"); null if standalone. */
  groupItemTitle: string | null;
  outcomes: string; // JSON-encoded array, e.g. '["Yes","No"]'
  outcomePrices: string;
  clobTokenIds: string;
  active: boolean;
  closed: boolean;
  acceptingOrders: boolean;
  startDate: string | null;
  endDate: string | null;
  endDateIso: string | null;
  icon: string | null;
  image: string | null;
  volume: string;
  liquidity: string;
  bestBid: number;
  bestAsk: number;
  lastTradePrice: number;
  spread: number;
}

export interface GammaEvent {
  id: string;
  slug: string;
  title: string;
  description: string;
  icon: string | null;
  category: string | null;
  startDate: string | null;
  endDate: string | null;
  markets: GammaMarket[];
}
