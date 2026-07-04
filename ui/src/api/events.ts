import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GammaEvent } from "@/types/gamma";
import type { Event, EventWithMarkets, ListEventsResponse } from "@/types/event";
import { gammaToMarket } from "@/api/markets";
import { isoToUnix } from "@/api/gamma-utils";
import { parseVolume } from "@/lib/format";

export const EVENTS_PAGE_SIZE = 20;

export interface ListEventsParams {
  limit: number;
  offset: number;
}

function gammaToEventWithMarkets(g: GammaEvent): EventWithMarkets {
  const event: Event = {
    event_id: Number(g.id),
    slug: g.slug,
    title: g.title,
    description: g.description,
    icon_url: g.icon,
    category: g.category,
    start_date: isoToUnix(g.startDate),
    end_date: isoToUnix(g.endDate),
    polymarket_event_id: null,
    volume_24hr: parseVolume(g.volume24hr),
  };
  return { event, markets: g.markets.map(gammaToMarket) };
}

export async function listEvents(
  params: ListEventsParams,
): Promise<ListEventsResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  const wire = await apiFetch<GammaEvent[]>(`/events?${search.toString()}`);
  // A fully-resolved event has nothing tradeable left — hide it from listings
  // (its price is frozen at the pre-resolution level and only confuses).
  // Direct links to the event page keep working; this filters the grid only.
  const live = wire.filter((g) => g.markets.some((m) => !m.closed));
  const events = live.map(gammaToEventWithMarkets);
  // Paging advances in WIRE units: the filter must not shift the server
  // offset, or the next page would re-fetch (and duplicate) skipped rows.
  return {
    events,
    nextOffset: params.offset + wire.length,
    hasMore: wire.length === params.limit,
    limit: params.limit,
    offset: params.offset,
  };
}

export async function getEvent(slug: string): Promise<EventWithMarkets> {
  const g = await apiFetch<GammaEvent>(`/events/${encodeURIComponent(slug)}`);
  return gammaToEventWithMarkets(g);
}

export function useEventsInfinite() {
  return useInfiniteQuery({
    queryKey: ["events", "infinite", EVENTS_PAGE_SIZE],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listEvents({ limit: EVENTS_PAGE_SIZE, offset: pageParam }),
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.nextOffset : undefined,
    // Poll so newly-synced markets appear on the home page without a manual
    // refresh (a sync streams markets in over a few seconds). Only refetches
    // while the tab is visible (refetchIntervalInBackground defaults to false).
    refetchInterval: 5000,
  });
}

export function useEvent(slug: string | undefined) {
  return useQuery({
    queryKey: ["event", slug],
    queryFn: () => {
      if (!slug) throw new Error("Event slug is required");
      return getEvent(slug);
    },
    enabled: Boolean(slug),
  });
}
