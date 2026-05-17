import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMarket } from "@/api/markets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MarketState } from "@/types/market";
import { OutcomeChips } from "@/components/orders/OutcomeChips";
import { Orderbook } from "@/components/orders/Orderbook";
import { OrderTicket } from "@/components/orders/OrderTicket";

const STATE_STYLES: Record<MarketState, string> = {
  DRAFT: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
  ACTIVE:
    "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200",
  CLOSED: "bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200",
  RESOLVED: "bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-200",
  CANCELLED:
    "bg-rose-100 text-rose-900 dark:bg-rose-900/30 dark:text-rose-200",
};

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
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6">
        <p className="text-sm font-medium text-destructive">
          Failed to load market
        </p>
        <p className="text-xs text-muted-foreground">
          {error instanceof Error ? error.message : "Market not found"}
        </p>
        <div className="flex gap-2">
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
            <Link to="/">Back to markets</Link>
          </Button>
        </div>
      </div>
    );
  }

  const isTradingDisabled = market.market_state !== "ACTIVE";
  const disabledReason = isTradingDisabled
    ? `Market is ${market.market_state}`
    : undefined;

  return (
    <article className="mx-auto max-w-5xl space-y-6">
      <Link
        to="/"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Back to markets
      </Link>

      <header className="space-y-3">
        <Badge
          variant="secondary"
          className={cn(
            "w-fit border-transparent",
            STATE_STYLES[market.market_state],
          )}
        >
          {market.market_state}
        </Badge>
        <h1 className="text-3xl font-bold tracking-tight">{market.question}</h1>
        {market.description ? (
          <p className="whitespace-pre-line text-sm text-muted-foreground">
            {market.description}
          </p>
        ) : null}
      </header>

      <OutcomeChips
        tokens={market.erc1155_tokens}
        selected={outcome}
        onSelect={setSelectedOutcome}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <Orderbook marketId={market.market_id} outcome={outcome} />
        <OrderTicket
          marketId={market.market_id}
          outcome={outcome}
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
    <article className="mx-auto max-w-5xl space-y-6">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-5 w-20 rounded-full" />
      <Skeleton className="h-9 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </article>
  );
}
