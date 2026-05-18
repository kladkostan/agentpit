import { useEffect, useMemo, useState } from "react";
import { useMarketsInfinite } from "@/api/markets";
import { Button } from "@/components/ui/button";
import {
  MarketGrid,
  MarketGridSkeleton,
} from "@/components/MarketGrid";
import type { Market } from "@/types/market";

const DATE_FMT = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
  year: "numeric",
});

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
  const today = useMemo(() => DATE_FMT.format(new Date()).toUpperCase(), []);

  const [query, setQuery] = useState("");
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
    if (trimmedQuery.length === 0) return markets;
    return markets.filter((m) =>
      m.question.toLowerCase().includes(trimmedQuery),
    );
  }, [markets, trimmedQuery]);

  const activeCount = useMemo(
    () => markets.filter((m) => m.market_state === "ACTIVE").length,
    [markets],
  );

  const isSearching = trimmedQuery.length > 0;

  return (
    <section className="space-y-10">
      <header className="space-y-6 border-b pb-8">
        <div className="flex items-end justify-between gap-6">
          <div className="space-y-3">
            <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-muted-foreground">
              AgentPit · Open order books
            </p>
            <h1 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight md:text-5xl">
              The Markets,
              <span className="font-display text-[1.15em] font-normal italic text-foreground/55">
                {" "}at a glance
              </span>
            </h1>
          </div>
          <div className="hidden flex-col items-end gap-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground md:flex">
            <span className="text-foreground/40">{today}</span>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
              />
              {activeCount} live
            </span>
          </div>
        </div>

        <SearchBar
          value={query}
          onChange={setQuery}
          shown={filtered.length}
          total={total}
        />
      </header>

      {isLoading ? (
        <MarketGridSkeleton />
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
        <MarketGrid
          markets={filtered}
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

function SearchBar({
  value,
  onChange,
  shown,
  total,
}: {
  value: string;
  onChange: (next: string) => void;
  shown: number;
  total: number | null;
}) {
  return (
    <div className="group flex items-center gap-3 border-b border-foreground/15 pb-2 transition-colors focus-within:border-foreground/60">
      <span aria-hidden className="text-muted-foreground/70">
        <SearchGlyph />
      </span>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Filter by question…"
        className="flex-1 bg-transparent py-1 font-sans text-base placeholder:text-muted-foreground/60 focus:outline-none"
      />
      <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground tabular-nums">
        {total === null ? (
          "loading"
        ) : (
          <>
            {shown}
            {total !== shown ? <span className="text-foreground/40"> / {total}</span> : null}
          </>
        )}
      </span>
    </div>
  );
}

function SearchGlyph() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
      aria-hidden
    >
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-4.65-4.65" />
    </svg>
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
