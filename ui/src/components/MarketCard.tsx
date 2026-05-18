import { Link } from "react-router-dom";
import { useOutcomeMid } from "@/lib/useYesMid";
import { cn } from "@/lib/utils";
import type { Market, MarketState } from "@/types/market";

interface MarketCardProps {
  market: Market;
  /** When provided, the card links to /events/:slug instead of /markets/:id.
   * Used for singleton-market events so the URL surface stays event-centric. */
  eventSlug?: string;
}

const STATE_TONE: Record<MarketState, { dot: string; label: string }> = {
  DRAFT: { dot: "bg-amber-500", label: "text-amber-700 dark:text-amber-400" },
  ACTIVE: {
    dot: "bg-emerald-500",
    label: "text-emerald-700 dark:text-emerald-400",
  },
  CLOSED: { dot: "bg-slate-400", label: "text-slate-600 dark:text-slate-300" },
  RESOLVED: { dot: "bg-sky-500", label: "text-sky-700 dark:text-sky-400" },
  CANCELLED: { dot: "bg-rose-500", label: "text-rose-700 dark:text-rose-400" },
};

const DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

function endLabel(seconds: number | null): string | null {
  if (seconds === null) return null;
  return DATE_FMT.format(new Date(seconds * 1000));
}

export function MarketCard({ market, eventSlug }: MarketCardProps) {
  const yesLabel = market.erc1155_tokens[0]?.[1];
  const { mid: yesMid } = useOutcomeMid(market.market_id, yesLabel);
  const yesCents = yesMid !== null ? Math.round(yesMid * 100) : null;
  const tone = STATE_TONE[market.market_state];
  const closes = endLabel(market.end_date);
  const href = eventSlug
    ? `/events/${eventSlug}`
    : `/markets/${market.market_id}`;

  return (
    <Link
      to={href}
      className="group relative block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <article className="flex h-full flex-col gap-5 rounded-2xl border bg-card p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-foreground/25 group-hover:shadow-[0_18px_36px_-22px_rgba(0,0,0,0.25)]">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className={cn("size-1.5 rounded-full", tone.dot)} />
            <span className={tone.label}>{market.market_state}</span>
          </span>
          <span>
            {closes ? (
              <>
                <span className="text-foreground/40">closes</span> {closes}
              </>
            ) : (
              <span className="text-foreground/40">#{market.market_id}</span>
            )}
          </span>
        </div>

        <h3 className="line-clamp-3 flex-1 text-[17px] font-medium leading-[1.3] tracking-tight text-balance">
          {market.question}
        </h3>

        {yesCents !== null ? (
          <ProbabilityRow yesPct={yesCents} />
        ) : (
          <div className="border-t pt-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              no book yet
            </span>
          </div>
        )}
      </article>
      <span
        aria-hidden
        className="pointer-events-none absolute right-5 top-1/2 -translate-y-1/2 translate-x-0 font-display text-2xl text-muted-foreground/0 transition-all duration-200 group-hover:translate-x-1 group-hover:text-muted-foreground"
      >
        →
      </span>
    </Link>
  );
}

function ProbabilityRow({ yesPct }: { yesPct: number }) {
  const noPct = 100 - yesPct;
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-1.5 text-emerald-700 dark:text-emerald-400">
          <span className="font-display text-4xl leading-none tabular-nums">
            {yesPct}
          </span>
          <span className="font-display text-2xl leading-none opacity-70">
            %
          </span>
          <span className="ml-1 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
            chance
          </span>
        </div>
        <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.22em]">
          <span className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
            <span aria-hidden className="size-1.5 rounded-full bg-emerald-500" />
            Yes
          </span>
          <span className="flex items-center gap-1.5 text-rose-700 dark:text-rose-400">
            <span aria-hidden className="size-1.5 rounded-full bg-rose-500" />
            No
          </span>
        </div>
      </div>
      <div
        className="relative h-1 overflow-hidden rounded-full bg-rose-500/15 dark:bg-rose-500/20"
        role="img"
        aria-label={`Yes ${yesPct}%, No ${noPct}%`}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-emerald-500"
          style={{ width: `${yesPct}%` }}
        />
      </div>
    </div>
  );
}
