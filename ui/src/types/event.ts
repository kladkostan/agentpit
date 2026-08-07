import type { Market } from "@/types/market";

export interface Event {
  event_id: number;
  slug: string;
  title: string;
  description: string;
  icon_url: string | null;
  category: string | null;
  start_date: number | null;
  end_date: number | null;
  polymarket_event_id: string | null;
  /** Upstream 24h volume in USD; null when never synced from upstream. */
  volume_24hr: number | null;
  /** Upstream all-time volume in USD; null when never synced from upstream.
   *  This is the figure the cards show — volume_24hr stays the ranking key. */
  volume: number | null;
  /** Order-book depth in USD; null when never synced from upstream. */
  liquidity: number | null;
  /** How contested the odds are, 0..1; null when never synced. */
  competitive: number | null;
}

export interface EventWithMarkets {
  event: Event;
  markets: Market[];
}

export interface ListEventsResponse {
  events: EventWithMarkets[];
  /** Server-side offset of the NEXT page, in wire units — client-side
   *  filtering (hidden resolved events) must not shift server paging. */
  nextOffset: number;
  /** True while the server keeps returning full pages. */
  hasMore: boolean;
  limit: number;
  offset: number;
}

export interface ListEventCategoriesResponse {
  categories: string[];
}
