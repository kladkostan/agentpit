import { useMemo } from "react";
import { useMarketsInfinite } from "@/api/markets";
import { Button } from "@/components/ui/button";
import {
  MarketGrid,
  MarketGridSkeleton,
} from "@/components/MarketGrid";
import type { Market } from "@/types/market";

export function MarketsPage() {
  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    refetch,
  } = useMarketsInfinite();

  const markets = useMemo<Market[]>(
    () => data?.pages.flatMap((page) => page.markets) ?? [],
    [data],
  );
  const total = data?.pages[0]?.total ?? null;

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-bold tracking-tight">Markets</h1>
        <p className="text-sm text-muted-foreground">
          {total === null
            ? "Loading available markets…"
            : `${total.toLocaleString()} ${total === 1 ? "market" : "markets"} available`}
        </p>
      </header>

      {isLoading ? (
        <MarketGridSkeleton />
      ) : error ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6">
          <p className="text-sm font-medium text-destructive">
            Failed to load markets
          </p>
          <p className="text-xs text-muted-foreground">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Retry
          </Button>
        </div>
      ) : markets.length === 0 ? (
        <div className="rounded-lg border bg-muted/20 p-10 text-center text-sm text-muted-foreground">
          No markets found
        </div>
      ) : (
        <MarketGrid
          markets={markets}
          hasNextPage={hasNextPage}
          isFetchingNextPage={isFetchingNextPage}
          onLoadMore={() => {
            void fetchNextPage();
          }}
        />
      )}
    </section>
  );
}
