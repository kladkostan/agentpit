import { useBook } from "@/api/orders";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  cumulativeTotals,
  levelsFrom,
  type OrderbookLevel,
} from "@/components/orders/orderMath";

interface OrderbookProps {
  tokenId: string;
  outcome: string;
}

const DEPTH = 8;

// Price is already dollars in [0, 1] → convert to cents with 1 decimal.
const formatCents = (dollars: number): string => (dollars * 100).toFixed(1);

const formatSize = (shares: number): string => {
  if (shares >= 1000) return `${(shares / 1000).toFixed(1)}k`;
  return shares.toFixed(2);
};

export function Orderbook({ tokenId, outcome }: OrderbookProps) {
  const { data, isLoading, error, isStale } = useBook(tokenId);

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

  const asks = levelsFrom(data.asks)
    .sort((a, b) => a.price - b.price)
    .slice(0, DEPTH)
    .reverse();
  const bids = levelsFrom(data.bids)
    .sort((a, b) => b.price - a.price)
    .slice(0, DEPTH);

  const maxSize = Math.max(
    1,
    ...asks.map((e) => e.size),
    ...bids.map((e) => e.size),
  );

  // TOTAL column: cumulative notional from the touch (spread) outward, per side.
  const askTotals = cumulativeTotals(asks, "ask");
  const bidTotals = cumulativeTotals(bids, "bid");

  const bestAskPrice = asks.length ? asks[asks.length - 1]!.price : null;
  const bestBidPrice = bids.length ? bids[0]!.price : null;
  const spread =
    bestAskPrice !== null && bestBidPrice !== null
      ? bestAskPrice - bestBidPrice
      : null;
  const mid =
    bestAskPrice !== null && bestBidPrice !== null
      ? (bestAskPrice + bestBidPrice) / 2
      : null;

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
          asks.map((entry, i) => (
            <Row
              key={`ask-${entry.price}`}
              entry={entry}
              kind="ask"
              maxSize={maxSize}
              total={askTotals[i]!}
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
          bids.map((entry, i) => (
            <Row
              key={`bid-${entry.price}`}
              entry={entry}
              kind="bid"
              maxSize={maxSize}
              total={bidTotals[i]!}
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
  total,
}: {
  entry: OrderbookLevel;
  kind: "ask" | "bid";
  maxSize: number;
  total: number;
}) {
  const price = formatCents(entry.price);
  const size = formatSize(entry.size);
  // Cumulative notional ($) from the touch outward (computed per side above).
  const totalLabel = total.toFixed(2);
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
        ${totalLabel}
      </span>
    </div>
  );
}
