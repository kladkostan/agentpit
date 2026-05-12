import { useOrderbook } from "@/api/orders";
import { Skeleton } from "@/components/ui/skeleton";
import type { OrderbookEntry } from "@/types/order";
import { SHARES_SCALE } from "@/components/orders/orderMath";

interface OrderbookProps {
  marketId: number;
  outcome: string;
}

const DEPTH = 8;

const formatPrice = (microUsdc: number): string =>
  (microUsdc / 1_000_000).toFixed(2);

const formatSize = (microShares: number): string =>
  (microShares / SHARES_SCALE).toFixed(2);

const aggregateByPrice = (entries: OrderbookEntry[]): OrderbookEntry[] => {
  const acc = new Map<number, OrderbookEntry>();
  for (const e of entries) {
    const existing = acc.get(e.PRICE);
    if (existing) {
      existing.REMAINING_AMOUNT += e.REMAINING_AMOUNT;
    } else {
      acc.set(e.PRICE, { ...e });
    }
  }
  return [...acc.values()];
};

export function Orderbook({ marketId, outcome }: OrderbookProps) {
  const { data, isLoading, error, isStale } = useOrderbook(marketId, outcome);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="text-sm text-muted-foreground">
        Orderbook unavailable — retrying.
      </p>
    );
  }

  const asks = aggregateByPrice(data.asks)
    .sort((a, b) => a.PRICE - b.PRICE)
    .slice(0, DEPTH)
    .reverse(); // display highest ask at top
  const bids = aggregateByPrice(data.bids)
    .sort((a, b) => b.PRICE - a.PRICE)
    .slice(0, DEPTH);

  return (
    <section className="space-y-2">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Orderbook — {outcome}
        </h2>
        {isStale ? (
          <span className="text-xs text-muted-foreground">stale</span>
        ) : null}
      </header>

      <div className="rounded-lg border">
        <div className="grid grid-cols-3 border-b bg-muted/30 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span>Price</span>
          <span className="text-right">Size</span>
          <span className="text-right">Total</span>
        </div>

        {asks.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">no asks</p>
        ) : (
          asks.map((entry) => (
            <Row key={entry.ORDER_ID} entry={entry} kind="ask" />
          ))
        )}

        <div className="border-t border-dashed" />

        {bids.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">no bids</p>
        ) : (
          bids.map((entry) => (
            <Row key={entry.ORDER_ID} entry={entry} kind="bid" />
          ))
        )}
      </div>
    </section>
  );
}

function Row({
  entry,
  kind,
}: {
  entry: OrderbookEntry;
  kind: "ask" | "bid";
}) {
  const price = formatPrice(entry.PRICE);
  const size = formatSize(entry.REMAINING_AMOUNT);
  const total = (
    (entry.PRICE / 1_000_000) *
    (entry.REMAINING_AMOUNT / SHARES_SCALE)
  ).toFixed(2);
  return (
    <div className="grid grid-cols-3 px-3 py-1.5 text-sm tabular-nums">
      <span
        className={
          kind === "ask"
            ? "text-rose-600 dark:text-rose-400"
            : "text-emerald-600 dark:text-emerald-400"
        }
      >
        ${price}
      </span>
      <span className="text-right">{size}</span>
      <span className="text-right text-muted-foreground">${total}</span>
    </div>
  );
}
