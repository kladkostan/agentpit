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
}

export interface EventWithMarkets {
  event: Event;
  markets: Market[];
}

export interface ListEventsResponse {
  events: EventWithMarkets[];
  total: number;
  limit: number;
  offset: number;
}
