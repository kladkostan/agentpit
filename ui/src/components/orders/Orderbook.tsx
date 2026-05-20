import { useOrderbook } from "@/api/orders";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  aggregateLevels,
  SHARES_SCALE,
  type OrderbookLevel,
} from "@/components/orders/orderMath";

interface OrderbookProps {
  marketId: number;
  outcome: string;
}

const DEPTH = 8;

// 0.1¢ tick → cents with 1 decimal, matching the spread/mid readout below.
const formatCents = (microUsdc: number): string =>
  (microUsdc / 10_000).toFixed(1);

const formatSize = (microShares: number): string => {
  const v = microShares / SHARES_SCALE;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v.toFixed(2);
};

export function Orderbook({ marketId, outcome }: OrderbookProps) {
  const { data, isLoading, error, isStale } = useOrderbook(marketId, outcome);

  if (isLoading) {
    return (
      <section className="space-y-3">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-72 w-full rounded-2xl" />
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="rounded-2xl border border-dashed bg-muted/20 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          Orderbook unavailable — retrying.
        </p>
      </section>
    );
  }

  const asks = aggregateLevels(data.asks)
    .sort((a, b) => a.price - b.price)
    .slice(0, DEPTH)
    .reverse();
  const bids = aggregateLevels(data.bids)
    .sort((a, b) => b.price - a.price)
    .slice(0, DEPTH);

  const maxSize = Math.max(
    1,
    ...asks.map((e) => e.size),
    ...bids.map((e) => e.size),
  );

  const bestAsk = asks.length ? asks[asks.length - 1]!.price / 1_000_000 : null;
  const bestBid = bids.length ? bids[0]!.price / 1_000_000 : null;
  const spread =
    bestAsk !== null && bestBid !== null ? bestAsk - bestBid : null;
  const mid =
    bestAsk !== null && bestBid !== null ? (bestAsk + bestBid) / 2 : null;

  return (
    <section className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-2xl leading-none tracking-tight">
            Order book
          </h2>
          <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
            {outcome}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
          {isStale ? (
            <span className="rounded-sm bg-amber-500/10 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">
              stale
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
              />
              live
            </span>
          )}
        </div>
      </header>

      <div className="overflow-hidden rounded-2xl border bg-card">
        <div className="grid grid-cols-[1fr_1fr_1fr] border-b bg-muted/30 px-5 py-2 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          <span>Price</span>
          <span className="text-right">Size</span>
          <span className="text-right">Total</span>
        </div>

        {asks.length === 0 ? (
          <p className="px-5 py-3 text-xs font-mono uppercase tracking-wider text-muted-foreground">
            no asks
          </p>
        ) : (
          asks.map((entry) => (
            <Row
              key={`ask-${entry.price}`}
              entry={entry}
              kind="ask"
              maxSize={maxSize}
            />
          ))
        )}

        <div className="flex items-center justify-between border-y bg-muted/20 px-5 py-2 font-mono text-[11px] tabular-nums">
          <span className="uppercase tracking-[0.2em] text-muted-foreground">
            spread
          </span>
          <span className="flex items-center gap-4">
            {mid !== null ? (
              <span className="text-muted-foreground">
                mid{" "}
                <span className="text-foreground">
                  {(mid * 100).toFixed(1)}¢
                </span>
              </span>
            ) : null}
            <span className="text-foreground">
              {spread !== null ? `${(spread * 100).toFixed(1)}¢` : "—"}
            </span>
          </span>
        </div>

        {bids.length === 0 ? (
          <p className="px-5 py-3 text-xs font-mono uppercase tracking-wider text-muted-foreground">
            no bids
          </p>
        ) : (
          bids.map((entry) => (
            <Row
              key={`bid-${entry.price}`}
              entry={entry}
              kind="bid"
              maxSize={maxSize}
            />
          ))
        )}
      </div>
    </section>
  );
}

function Row({
  entry,
  kind,
  maxSize,
}: {
  entry: OrderbookLevel;
  kind: "ask" | "bid";
  maxSize: number;
}) {
  const price = formatCents(entry.price);
  const size = formatSize(entry.size);
  const total = (
    (entry.price / 1_000_000) *
    (entry.size / SHARES_SCALE)
  ).toFixed(2);
  const depthPct = Math.min(100, (entry.size / maxSize) * 100);
  return (
    <div className="relative grid grid-cols-[1fr_1fr_1fr] px-5 py-1.5 font-mono text-[13px] tabular-nums">
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 right-0 transition-[width] duration-300",
          kind === "ask"
            ? "bg-rose-500/[0.08] dark:bg-rose-400/[0.10]"
            : "bg-emerald-500/[0.08] dark:bg-emerald-400/[0.10]",
        )}
        style={{ width: `${depthPct}%` }}
      />
      <span
        className={cn(
          "relative",
          kind === "ask"
            ? "text-rose-600 dark:text-rose-400"
            : "text-emerald-600 dark:text-emerald-400",
        )}
      >
        {price}¢
      </span>
      <span className="relative text-right">{size}</span>
      <span className="relative text-right text-muted-foreground">
        ${total}
      </span>
    </div>
  );
}
