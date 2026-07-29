import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useEvent } from "@/api/events";
import { EventChart } from "@/components/EventChart";
import { EventLeaderboardRow } from "@/components/EventLeaderboardRow";
import { Orderbook } from "@/components/orders/Orderbook";
import { OrderTicket } from "@/components/orders/OrderTicket";
import { RotatingSeriesPanel } from "@/components/RotatingSeriesPanel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { sortMarketsByYesMid } from "@/lib/eventOutcomes";
import { detectRotatingSeries } from "@/lib/rotatingSeries";
import { formatLongDate } from "@/lib/format";
import { useYesMidMap } from "@/lib/useYesMid";
import type { MarketState } from "@/types/market";

const NON_TRADEABLE: ReadonlySet<MarketState> = new Set([
  "RESOLVED",
  "CANCELLED",
  "CLOSED",
]);

function disabledReasonFor(state: MarketState): string | undefined {
  if (state === "RESOLVED") return "Market resolved";
  if (state === "CANCELLED") return "Market cancelled";
  if (state === "CLOSED") return "Market closed";
  if (state === "DRAFT") return "Market not yet active";
  return undefined;
}

export function EventDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data, isLoading, error, refetch } = useEvent(slug);
  const [selection, setSelection] = useState<{
    marketId: number;
    outcome: string;
  } | null>(null);
  // Track whether we've already auto-selected for the current slug. Without
  // this, toggling the auto-selected row to `null` would trigger an immediate
  // re-selection on the next render — the row would never visually collapse.
  const autoSelectedSlugRef = useRef<string | null>(null);

  useEffect(() => {
    setSelection(null);
    autoSelectedSlugRef.current = null;
  }, [slug]);

  const midByMarket = useYesMidMap(data?.markets ?? []);
  const ordered = useMemo(
    () => (data ? sortMarketsByYesMid(data.markets, midByMarket) : []),
    [data, midByMarket],
  );

  // A recurring "rotating series" (e.g. BTC Up or Down 5m) gets a dedicated
  // live-window view instead of the probability leaderboard. Detected from the
  // markets' disjoint sequential time windows.
  const series = useMemo(
    () =>
      data
        ? detectRotatingSeries(data.markets, Math.floor(Date.now() / 1000))
        : null,
    [data],
  );

  // Default-select once per slug, so user toggles can actually deselect. For a
  // rotating series, select the LIVE window (not the top-probability one, which
  // is often the just-closed window); otherwise the top-ranked outcome.
  useEffect(() => {
    if (!slug || autoSelectedSlugRef.current === slug) return;
    const first = series?.live ?? ordered[0];
    if (!first) return;
    const label = first.erc1155_tokens[0]?.[1];
    if (!label) return;
    autoSelectedSlugRef.current = slug;
    setSelection({ marketId: first.market_id, outcome: label });
  }, [ordered, series, slug]);

  if (isLoading) return <EventDetailSkeleton />;

  if (error || !data) {
    return (
      <div className="mx-auto max-w-2xl rounded-2xl border border-destructive/30 bg-destructive/5 p-8">
        <p className="text-2xl font-semibold tracking-tight">
          Couldn't load this event
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          {error instanceof Error ? error.message : "Event not found"}
        </p>
        <div className="mt-6 flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Retry
          </Button>
          <Link to="/markets">
            <Button variant="ghost" size="sm">
              ← Back
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const { event, markets } = data;
  const endLabel = formatLongDate(event.end_date);
  const isSingleMarket = markets.length === 1;
  const onlyMarket = markets[0] ?? null;

  const selectedMarket =
    selection !== null
      ? markets.find((m) => m.market_id === selection.marketId) ?? null
      : null;
  const selectedOutcome = selection?.outcome ?? null;
  const disabledReason = selectedMarket
    ? disabledReasonFor(selectedMarket.market_state)
    : undefined;

  return (
    <section className="space-y-10 animate-fade-up">
      <header className="space-y-5 pb-8">
        <div className="flex items-center gap-2.5 font-mono text-[10px] uppercase tracking-[0.24em] text-muted-foreground">
          <span
            aria-hidden
            className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
          />
          Event · {markets.length}{" "}
          {markets.length === 1 ? "outcome" : "outcomes"}
          {event.category ? (
            <>
              <span className="text-foreground/30">/</span>
              {event.category}
            </>
          ) : null}
        </div>

        <div className="flex items-start gap-5">
          {event.icon_url ? (
            <img
              src={event.icon_url}
              alt=""
              className="size-14 rounded-xl object-cover ring-1 ring-border"
              loading="lazy"
            />
          ) : null}
          <h1 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight md:text-5xl">
            {event.title}
          </h1>
        </div>

        <div className="flex flex-wrap gap-x-5 gap-y-2 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          {endLabel ? (
            <span>
              <span className="text-foreground/40">Closes</span> {endLabel}
            </span>
          ) : null}
          {series ? (
            <span>
              <span className="text-foreground/40">Rotating</span> live windows
            </span>
          ) : !isSingleMarket ? (
            <span>
              <span className="text-foreground/40">Sorted by</span> highest chance
            </span>
          ) : null}
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-8">
          {/* A rotating series has no useful long-range chart (each window is
              minutes long); the live-window panel is the hero instead. */}
          {series ? null : (
            <EventChart markets={markets} midByMarket={midByMarket} />
          )}

          {isSingleMarket && onlyMarket ? (
            <div className="rounded-2xl border bg-card/40 px-5 py-5">
              <Orderbook
                tokenId={(() => {
                  const outcomeLabel = selection?.outcome || onlyMarket.erc1155_tokens[0]?.[1] || "";
                  return onlyMarket.erc1155_tokens.find(([, label]) => label === outcomeLabel)?.[0] ?? "";
                })()}
                outcome={
                  selection?.outcome ||
                  onlyMarket.erc1155_tokens[0]?.[1] ||
                  ""
                }
              />
            </div>
          ) : series ? (
            <RotatingSeriesPanel
              series={series}
              selectedMarketId={selection?.marketId ?? null}
              selectedOutcome={selection?.outcome ?? null}
              onSelectWindow={(marketId, outcome) =>
                setSelection({ marketId, outcome })
              }
            />
          ) : (
            <div className="rounded-2xl border bg-card/40">
              {ordered.map((market, idx) => {
                const isExpanded = selection?.marketId === market.market_id;
                const yesLabel = market.erc1155_tokens[0]?.[1] ?? "";
                return (
                  <Fragment key={market.market_id}>
                    <EventLeaderboardRow
                      market={market}
                      rank={idx + 1}
                      isSelected={isExpanded}
                      selectedOutcome={isExpanded ? selection.outcome : null}
                      onToggleMarket={(marketId, outcome) =>
                        setSelection((prev) =>
                          prev?.marketId === marketId
                            ? null
                            : { marketId, outcome },
                        )
                      }
                      onPickOutcome={(marketId, outcome) =>
                        setSelection({ marketId, outcome })
                      }
                    />
                    {isExpanded ? (
                      <div className="border-b border-border/60 bg-foreground/[0.02] px-5 py-4 animate-fade-up">
                        <Orderbook
                          tokenId={market.erc1155_tokens.find(([, label]) => label === (selection.outcome || yesLabel))?.[0] ?? ""}
                          outcome={selection.outcome || yesLabel}
                        />
                      </div>
                    ) : null}
                  </Fragment>
                );
              })}
            </div>
          )}

          {event.description ? (
            <section className="space-y-3">
              <h2 className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                About this market
              </h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {event.description}
              </p>
            </section>
          ) : null}
        </div>

        <aside className="lg:sticky lg:top-20 lg:self-start">
          {selectedMarket ? (
            <OrderTicket
              key={selectedMarket.market_id}
              marketId={selectedMarket.market_id}
              tokens={selectedMarket.erc1155_tokens}
              outcome={selectedOutcome ?? selectedMarket.erc1155_tokens[0]![1]}
              question={selectedMarket.question}
              endDate={selectedMarket.end_date}
              isTradingDisabled={NON_TRADEABLE.has(selectedMarket.market_state)}
              {...(disabledReason !== undefined ? { disabledReason } : {})}
              onOutcomeChange={(outcome) =>
                setSelection({ marketId: selectedMarket.market_id, outcome })
              }
            />
          ) : (
            <div className="rounded-2xl border bg-card/40 p-8 text-center">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                Select an outcome to trade
              </p>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function EventDetailSkeleton() {
  return (
    <section className="space-y-10">
      <div className="space-y-5 border-b pb-8">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-12 w-full max-w-xl" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="rounded-2xl border">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="grid grid-cols-[40px_44px_1fr_72px_auto] items-center gap-4 border-b border-border/60 px-3 py-3 last:border-0"
            >
              <Skeleton className="h-3 w-6" />
              <Skeleton className="size-9 rounded-md" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-6 w-12" />
              <div className="flex gap-1.5">
                <Skeleton className="h-10 w-20 rounded-lg" />
                <Skeleton className="h-10 w-20 rounded-lg" />
              </div>
            </div>
          ))}
        </div>
        <Skeleton className="h-[520px] w-full rounded-2xl" />
      </div>
    </section>
  );
}
