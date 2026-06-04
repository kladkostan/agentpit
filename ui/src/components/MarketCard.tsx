import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import { useSparkline } from "@/api/markets";
import { CHART_PRIMARY_COLOR } from "@/lib/chartPalette";
import { formatProbabilityPct, formatShortDate, formatVolume } from "@/lib/format";
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

export function MarketCard({ market, eventSlug }: MarketCardProps) {
  const yesTokenId = market.erc1155_tokens[0]?.[0];
  const yesLabel = market.erc1155_tokens[0]?.[1];
  const { mid: yesMid } = useOutcomeMid(yesTokenId);
  const { data: spark } = useSparkline(market.market_id, yesLabel);
  const yesPctLabel = formatProbabilityPct(yesMid);
  const tone = STATE_TONE[market.market_state];
  const closes = formatShortDate(market.end_date);
  const href = eventSlug
    ? `/events/${eventSlug}`
    : `/markets/${market.market_id}`;

  const points = spark?.points ?? [];
  // Change is expressed in percentage points of probability (Δcents).
  // Sparkline prices are micro-USDC ∈ [0, 1_000_000] → divide by 10_000 to
  // get cents, then round to an integer delta.
  const change =
    points.length >= 2
      ? Math.round(
          (points[points.length - 1]!.p - points[0]!.p) / 10_000,
        )
      : null;
  const volumeUsd = spark ? spark.volume_total_micro_usd / 1_000_000 : 0;

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

        <div className="flex items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <div
              className={cn(
                "flex items-baseline gap-1",
                yesMid === null
                  ? "text-muted-foreground/50"
                  : "text-foreground",
              )}
            >
              <span className="text-[44px] font-semibold leading-none tracking-tight tabular-nums">
                {yesPctLabel}
              </span>
              <span className="text-xl font-semibold leading-none opacity-60">
                %
              </span>
            </div>
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              chance
            </span>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Sparkline
              points={points}
              strokeColor={CHART_PRIMARY_COLOR}
              width={180}
              height={56}
              className="shrink-0"
            />
            <TodayChange change={change} />
          </div>
        </div>

        {volumeUsd > 0 ? (
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground/80 tabular-nums">
            {formatVolume(volumeUsd)} <span className="text-foreground/40">vol</span>
          </div>
        ) : null}
      </article>
    </Link>
  );
}

/** Renders the trailing-24h price change. Up/down moves get a sky-blue
 *  arrow + magnitude; a zero net move shows a muted "flat today" so the
 *  card doesn't look identical to one that has no trade history yet. */
function TodayChange({ change }: { change: number | null }) {
  if (change === null) return null;
  if (change === 0) {
    return (
      <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground/70">
        flat today
      </span>
    );
  }
  const isUp = change > 0;
  return (
    <span className="flex items-center gap-0.5 font-mono text-[10px] uppercase tracking-[0.22em] tabular-nums text-sky-700 dark:text-sky-400">
      <span aria-hidden>{isUp ? "↑" : "↓"}</span>
      {Math.abs(change)}% today
    </span>
  );
}
