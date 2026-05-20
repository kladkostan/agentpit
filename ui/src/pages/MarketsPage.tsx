import { useEffect, useMemo } from "react";
import { useEventsInfinite } from "@/api/events";
import { Button } from "@/components/ui/button";
import {
  EventGrid,
  EventGridSkeleton,
} from "@/components/EventGrid";
import { useSearch } from "@/lib/searchContext";
import type { EventWithMarkets } from "@/types/event";

export function MarketsPage() {
  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useEventsInfinite();

  const events = useMemo<EventWithMarkets[]>(
    () => data?.pages.flatMap((page) => page.events) ?? [],
    [data],
  );
  const { query, setQuery } = useSearch();
  const trimmedQuery = query.trim().toLowerCase();

  // When the user starts searching, eagerly pull remaining pages so the
  // client-side filter sees the whole dataset rather than only the loaded
  // window.
  useEffect(() => {
    if (trimmedQuery.length > 0 && hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [trimmedQuery, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const filtered = useMemo(() => {
    if (trimmedQuery.length === 0) return events;
    return events.filter(({ event, markets }) => {
      if (event.title.toLowerCase().includes(trimmedQuery)) return true;
      return markets.some((m) =>
        (m.outcome_label ?? m.question).toLowerCase().includes(trimmedQuery),
      );
    });
  }, [events, trimmedQuery]);

  const activeCount = useMemo(
    () =>
      events.reduce(
        (acc, ev) =>
          acc +
          ev.markets.filter((m) => m.market_state === "ACTIVE").length,
        0,
      ),
    [events],
  );

  const isSearching = trimmedQuery.length > 0;

  return (
    <section className="space-y-8">
      <header className="flex items-center justify-end gap-6 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
          />
          {activeCount} live
        </span>
      </header>

      {isLoading ? (
        <EventGridSkeleton />
      ) : error ? (
        <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-8">
          <p className="text-xl font-semibold tracking-tight">
            Failed to load markets
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => {
              void refetch();
            }}
          >
            Retry
          </Button>
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState query={query} onClear={() => setQuery("")} />
      ) : (
        <EventGrid
          events={filtered}
          hasNextPage={!isSearching && hasNextPage}
          isFetchingNextPage={isFetchingNextPage}
          onLoadMore={() => {
            void fetchNextPage();
          }}
        />
      )}
    </section>
  );
}

function EmptyState({
  query,
  onClear,
}: {
  query: string;
  onClear: () => void;
}) {
  return (
    <div className="rounded-2xl border border-dashed bg-muted/20 px-8 py-16 text-center">
      <p className="text-2xl font-semibold tracking-tight">No matches</p>
      <p className="mt-2 text-sm text-muted-foreground">
        Nothing matches “{query}”. Try a different question.
      </p>
      <Button
        variant="outline"
        size="sm"
        className="mt-6"
        onClick={onClear}
      >
        Clear filter
      </Button>
    </div>
  );
}
