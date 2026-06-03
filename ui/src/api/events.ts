import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { GammaEvent } from "@/types/gamma";
import type { Event, EventWithMarkets, ListEventsResponse } from "@/types/event";
import { gammaToMarket } from "@/api/markets";
import { isoToUnix } from "@/api/gamma-utils";

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
  const events = wire.map(gammaToEventWithMarkets);
  // Gamma returns a bare array with no total; derive a total that keeps the
  // infinite query paging while pages come back full, stopping on a short page.
  const total =
    params.offset + events.length + (events.length === params.limit ? 1 : 0);
  return { events, total, limit: params.limit, offset: params.offset };
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
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.events.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
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
