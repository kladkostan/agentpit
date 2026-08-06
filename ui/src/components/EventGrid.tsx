import { useEffect, useRef } from "react";
import { MarketCard } from "@/components/MarketCard";
import { MultiMarketEventCard } from "@/components/MultiMarketEventCard";
import { Skeleton } from "@/components/ui/skeleton";
import type { EventWithMarkets } from "@/types/event";

interface EventGridProps {
  events: EventWithMarkets[];
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
  /** Which volume figure the cards show, following the list's sort. */
  volumePrefer?: "total" | "24h";
}

export function EventGrid({
  events,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
  volumePrefer = "total",
}: EventGridProps) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNextPage) return;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting) onLoadMore();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, onLoadMore]);

  return (
    <>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {events.map(({ event, markets }) =>
          markets.length === 1 ? (
            <MarketCard
              key={event.event_id}
              market={markets[0]!}
              eventSlug={event.slug}
              volume={event.volume}
              volume24hr={event.volume_24hr}
              volumePrefer={volumePrefer}
            />
          ) : (
            <MultiMarketEventCard
              key={event.event_id}
              event={event}
              markets={markets}
              volumePrefer={volumePrefer}
            />
          ),
        )}
      </div>
      {hasNextPage ? (
        <div
          ref={sentinelRef}
          className="mt-6 flex h-12 items-center justify-center"
        >
          {isFetchingNextPage ? <LoadingSpinner /> : null}
        </div>
      ) : null}
    </>
  );
}

export function EventGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }, (_, idx) => (
        <div
          key={idx}
          className="flex h-full flex-col gap-5 rounded-2xl border bg-card p-5"
        >
          <div className="flex items-center justify-between">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-20" />
          </div>
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-5/6" />
            <Skeleton className="h-5 w-2/3" />
          </div>
          <div className="flex items-end justify-between border-t pt-4">
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-3 w-14" />
          </div>
        </div>
      ))}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div
      role="status"
      className="size-5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground"
      aria-label="Loading more events"
    />
  );
}
