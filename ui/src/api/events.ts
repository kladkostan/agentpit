import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  EventWithMarkets,
  ListEventCategoriesResponse,
  ListEventsResponse,
} from "@/types/event";

export const EVENTS_PAGE_SIZE = 20;

export interface ListEventsParams {
  limit: number;
  offset: number;
  category?: string;
}

export async function listEvents(
  params: ListEventsParams,
): Promise<ListEventsResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.category) {
    search.set("category", params.category);
  }
  return apiFetch<ListEventsResponse>(`/events?${search.toString()}`);
}

export async function listEventCategories(): Promise<ListEventCategoriesResponse> {
  return apiFetch<ListEventCategoriesResponse>("/events/categories");
}

export async function getEvent(slug: string): Promise<EventWithMarkets> {
  return apiFetch<EventWithMarkets>(`/events/${encodeURIComponent(slug)}`);
}

export function useEventsInfinite(category: string | null = null) {
  const normalizedCategory = category?.trim() || null;
  return useInfiniteQuery({
    queryKey: ["events", "infinite", EVENTS_PAGE_SIZE, normalizedCategory],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      listEvents({
        limit: EVENTS_PAGE_SIZE,
        offset: pageParam,
        category: normalizedCategory ?? undefined,
      }),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.events.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });
}

export function useEventCategories() {
  return useQuery({
    queryKey: ["events", "categories"],
    queryFn: listEventCategories,
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
