import { useEffect, useRef } from "react";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketCard } from "@/components/MarketCard";
import type { Market } from "@/types/market";

interface MarketGridProps {
  markets: Market[];
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}

export function MarketGrid({
  markets,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: MarketGridProps) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNextPage) {
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting) {
        onLoadMore();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, onLoadMore]);

  return (
    <>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {markets.map((market) => (
          <MarketCard key={market.market_id} market={market} />
        ))}
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

export function MarketGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }, (_, idx) => (
        <Card key={idx} className="flex h-full flex-col">
          <CardHeader className="space-y-3 pb-3">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </CardHeader>
          <CardContent className="flex-1 pb-3" />
          <CardFooter className="gap-2">
            <Skeleton className="h-9 flex-1" />
            <Skeleton className="h-9 flex-1" />
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div
      role="status"
      className="size-5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground"
      aria-label="Loading more markets"
    />
  );
}
