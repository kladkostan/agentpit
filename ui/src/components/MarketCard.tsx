import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Sparkline";
import { usePricesHistory } from "@/api/markets";
import { CHART_PRIMARY_COLOR } from "@/lib/chartPalette";
import {
  formatProbabilityPct,
  formatShortDate,
  formatVolume,
  volumeStat,
} from "@/lib/format";
import { STATE_TONE } from "@/lib/marketState";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/market";

interface MarketCardProps {
  market: Market;
  /** When provided, the card links to /events/:slug instead of /markets/:id.
   * Used for singleton-market events so the URL surface stays event-centric. */
  eventSlug?: string;
  /** Parent event's upstream volumes (USD). All-time is preferred; the 24h
   *  figure is the fallback for events no longer in the synced set. */
  volume?: number | null;
  volume24hr?: number | null;
}

export function MarketCard({
  market,
  eventSlug,
  volume,
  volume24hr,
}: MarketCardProps) {
  const yesTokenId = market.erc1155_tokens[0]?.[0];
  const yesPrice = market.outcome_prices[0];
  const { data: spark } = usePricesHistory(yesTokenId);
  const yesPctLabel = formatProbabilityPct(yesPrice ?? null);
  const tone = STATE_TONE[market.market_state];
  const closes = formatShortDate(market.end_date);
  const vol = volumeStat(volume ?? null, volume24hr ?? null);
  const href = eventSlug
    ? `/events/${eventSlug}`
    : `/markets/${market.market_id}`;

  const points = spark?.history ?? [];
  // Change is expressed in percentage points of probability (Δcents).
  // Prices are probabilities in [0, 1] → multiply by 100 to get cents.
  const change =
    points.length >= 2
      ? Math.round(
          (points[points.length - 1]!.p - points[0]!.p) * 100,
        )
      : null;

  // `isolate` keeps every z-index inside the card inside the card. Without it
  // the probability's `z-10` competed with the sticky header's `z-10`, and
  // since the cards come later in the DOM the number won the tie: it painted
  // over the header and intercepted clicks meant for the search box.
  return (
    <Link
      to={href}
      className="group relative isolate block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <article className="flex h-full flex-col gap-5 rounded-2xl border bg-card p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-foreground/25 group-hover:shadow-[0_18px_36px_-22px_rgba(0,0,0,0.25)]">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {/* Only a state worth remarking on. Every card on a list filtered to
              live markets said ACTIVE, so the badge marked nothing — while
              RESOLVED or CANCELLED changes what the card means. */}
          {market.market_state === "ACTIVE" ? (
            <span />
          ) : (
            <span className="flex min-w-0 items-center gap-1.5">
              <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", tone.dot)} />
              <span className={cn("truncate", tone.label)}>{market.market_state}</span>
            </span>
          )}
          <span className="shrink-0 whitespace-nowrap">
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
          {/* The sparkline is wider than the space left for it, so the two
              overlap on a narrow card. Being later in the DOM it used to paint
              on top of the probability; `relative z-10` puts the number in
              front, where the reader needs it. */}
          <div className="relative z-10 flex min-w-0 flex-col gap-1">
            <div
              className={cn(
                "flex items-baseline gap-1",
                yesPrice === undefined
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

        {vol ? (
          <div className="flex items-center gap-1.5 border-t pt-3 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            <span className="tabular-nums text-foreground/70">
              {formatVolume(vol.value)}
            </span>
            <span>{vol.label}</span>
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
