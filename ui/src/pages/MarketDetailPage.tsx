import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMarket } from "@/api/markets";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { closeLabel } from "@/lib/format";
import { STATE_TONE } from "@/lib/marketState";
import { cn } from "@/lib/utils";
import { Orderbook } from "@/components/orders/Orderbook";
import { OrderTicket } from "@/components/orders/OrderTicket";

const DATE_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

function formatTs(seconds: number | null): string | null {
  if (seconds === null) return null;
  return DATE_FORMAT.format(new Date(seconds * 1000));
}

/** API sometimes wraps condition_id as `{ value: string }`. Normalize. */
function unwrapHex(value: unknown): string | null {
  if (typeof value === "string" && value.length > 0) return value;
  if (
    value &&
    typeof value === "object" &&
    "value" in value &&
    typeof (value as { value: unknown }).value === "string"
  ) {
    return (value as { value: string }).value;
  }
  return null;
}

function shortHex(hex: string): string {
  if (hex.length <= 12) return hex;
  return `${hex.slice(0, 6)}…${hex.slice(-4)}`;
}

export function MarketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: market, isLoading, error, refetch } = useMarket(id);

  const firstOutcome = useMemo(
    () => market?.erc1155_tokens[0]?.[1] ?? "",
    [market],
  );
  const [selectedOutcome, setSelectedOutcome] = useState<string>(firstOutcome);
  const outcome = selectedOutcome || firstOutcome;

  if (isLoading) {
    return <MarketDetailSkeleton />;
  }

  if (error || !market) {
    return (
      <div className="mx-auto max-w-2xl rounded-2xl border border-destructive/30 bg-destructive/5 p-8">
        <p className="text-2xl font-semibold tracking-tight">
          Couldn't load this market
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          {error instanceof Error ? error.message : "Market not found"}
        </p>
        <div className="mt-6 flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Retry
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/markets">Back to markets</Link>
          </Button>
        </div>
      </div>
    );
  }

  const isTradingDisabled = market.market_state !== "ACTIVE";
  const disabledReason = isTradingDisabled
    ? `Market is ${market.market_state}`
    : undefined;

  const stateTone = STATE_TONE[market.market_state];
  const startLabel = formatTs(market.start_date);
  const closes = closeLabel(
    market.end_date,
    market.market_state,
    Date.now() / 1000,
    formatTs,
  );
  const conditionHex = unwrapHex(market.condition_id);

  return (
    <article className="mx-auto w-full max-w-6xl animate-fade-up space-y-10">
      <nav className="flex items-center justify-between text-[11px] font-mono uppercase tracking-[0.22em] text-muted-foreground">
        <Link
          to="/markets"
          className="group flex items-center gap-2 transition-colors hover:text-foreground"
        >
          <span
            aria-hidden
            className="transition-transform group-hover:-translate-x-0.5"
          >
            ←
          </span>
          <span>Markets</span>
        </Link>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className={cn("size-1.5 rounded-full", stateTone.dot)}
            />
            <span className={stateTone.label}>{market.market_state}</span>
          </span>
          {closes ? (
            <span>
              {closes.prefix ? (
                <span className="text-foreground/40">{closes.prefix} </span>
              ) : null}
              {closes.value}
            </span>
          ) : null}
          <span className="text-foreground/40">#{market.market_id}</span>
        </div>
      </nav>

      <header className="space-y-6">
        <h1 className="text-balance text-3xl font-semibold leading-[1.15] tracking-tight md:text-[40px] md:leading-[1.1]">
          {market.question}
        </h1>
        {startLabel || conditionHex || market.polymarket_id !== null ? (
          <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            {startLabel ? (
              <div className="flex items-center gap-1.5">
                <dt className="text-foreground/40">opened</dt>
                <dd className="text-foreground/80">{startLabel}</dd>
              </div>
            ) : null}
            {market.polymarket_id !== null ? (
              <div className="flex items-center gap-1.5">
                <dt className="text-foreground/40">polymarket</dt>
                <dd className="text-foreground/80">#{market.polymarket_id}</dd>
              </div>
            ) : null}
            {conditionHex ? (
              <div className="flex items-center gap-1.5">
                <dt className="text-foreground/40">condition</dt>
                <dd className="text-foreground/80">{shortHex(conditionHex)}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-8">
          <Orderbook
            tokenId={market.erc1155_tokens.find(([, label]) => label === outcome)?.[0] ?? ""}
            outcome={outcome}
          />
          {market.description ? (
            <section className="space-y-3 border-t pt-6">
              <h2 className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                About this market
              </h2>
              <p className="whitespace-pre-line text-pretty text-base leading-relaxed text-foreground/80">
                {market.description}
              </p>
            </section>
          ) : null}
        </div>
        <OrderTicket
          marketId={market.market_id}
          tokens={market.erc1155_tokens}
          outcome={outcome}
          question={market.question}
          endDate={market.end_date}
          onOutcomeChange={setSelectedOutcome}
          isTradingDisabled={isTradingDisabled}
          {...(disabledReason !== undefined ? { disabledReason } : {})}
        />
      </div>
    </article>
  );
}

function MarketDetailSkeleton() {
  return (
    <article className="mx-auto w-full max-w-6xl space-y-10">
      <div className="flex items-center justify-between">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-40" />
      </div>
      <div className="space-y-4">
        <Skeleton className="h-14 w-4/5" />
        <Skeleton className="h-14 w-3/5" />
      </div>
      <Skeleton className="h-28 w-full rounded-2xl" />
      <div className="grid gap-8 lg:grid-cols-[1fr_22rem]">
        <Skeleton className="h-80 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    </article>
  );
}
