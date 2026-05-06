import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { ProbabilityBadge } from "@/components/ProbabilityBadge";
import { cn } from "@/lib/utils";
import type { Market, MarketState } from "@/types/market";

interface MarketCardProps {
  market: Market;
}

const STATE_STYLES: Record<MarketState, string> = {
  DRAFT: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
  ACTIVE:
    "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200",
  CLOSED: "bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200",
  RESOLVED: "bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-200",
  CANCELLED:
    "bg-rose-100 text-rose-900 dark:bg-rose-900/30 dark:text-rose-200",
};

export function MarketCard({ market }: MarketCardProps) {
  return (
    <Link
      to={`/markets/${market.market_id}`}
      className="group block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <Card className="flex h-full flex-col transition-shadow group-hover:shadow-md">
        <CardHeader className="space-y-3 pb-3">
          <Badge
            variant="secondary"
            className={cn(
              "w-fit border-transparent",
              STATE_STYLES[market.market_state],
            )}
          >
            {market.market_state}
          </Badge>
          <h3 className="line-clamp-3 text-base font-semibold leading-snug">
            {market.question}
          </h3>
        </CardHeader>
        <CardContent className="flex-1 pb-3" />
        <CardFooter className="gap-2">
          <ProbabilityBadge side="yes" probability={null} />
          <ProbabilityBadge side="no" probability={null} />
        </CardFooter>
      </Card>
    </Link>
  );
}
