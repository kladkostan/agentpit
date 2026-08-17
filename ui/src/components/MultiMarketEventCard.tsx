import { useMemo } from "react";
import { Link } from "react-router-dom";
import { sortMarketsByYesMid, yesPriceMap } from "@/lib/eventOutcomes";
import {
  closeLabel,
  formatProbabilityPct,
  formatVolume,
  volumeStat,
} from "@/lib/format";
import { STATE_TONE, eventState } from "@/lib/marketState";
import { cn } from "@/lib/utils";
import type { Event } from "@/types/event";
import type { Market } from "@/types/market";

interface MultiMarketEventCardProps {
  event: Event;
  markets: Market[];
  /** Which volume figure to show — set from the list's sort so the number on
   *  the card explains the order it is in. */
  volumePrefer?: "total" | "24h";
}

const PREVIEW_COUNT = 2;

function OutcomeIcon({ market }: { market: Market }) {
  const icon = market.icon_url;
  if (icon && (icon.startsWith("http") || icon.startsWith("/"))) {
    return (
      <img
        src={icon}
        alt=""
        className="size-6 rounded-sm object-cover"
        loading="lazy"
      />
    );
  }
  return (
    <span
      aria-hidden
      className="flex size-6 items-center justify-center rounded-sm bg-secondary text-sm leading-none"
    >
      {icon ?? "•"}
    </span>
  );
}

function PreviewRow({
  market,
  mid,
}: {
  market: Market;
  mid: number | undefined;
}) {
  const pctLabel = formatProbabilityPct(mid ?? null);
  const label = market.outcome_label ?? market.question;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <OutcomeIcon market={market} />
      <span className="flex-1 truncate text-sm">{label}</span>
      <span
        className={cn(
          "text-lg font-semibold leading-none tabular-nums",
          mid === undefined && "text-muted-foreground/40",
        )}
      >
        {pctLabel}
        <span className="ml-0.5 text-xs font-semibold opacity-60">%</span>
      </span>
    </div>
  );
}

export function MultiMarketEventCard({
  event,
  markets,
  volumePrefer = "total",
}: MultiMarketEventCardProps) {
  const midByMarket = useMemo(() => yesPriceMap(markets), [markets]);
  const ranked = useMemo(
    () => sortMarketsByYesMid(markets, midByMarket),
    [markets, midByMarket],
  );
  const previewMarkets = ranked.slice(0, PREVIEW_COUNT);
  const extra = ranked.length - previewMarkets.length;
  const vol = volumeStat(event.volume, event.volume_24hr, volumePrefer);
  // Same badge as a single-market card: the two card shapes describe the same
  // thing, so they must not label it differently. The outcome count is still on
  // the card, in the "+N more outcomes" line below the preview.
  const state = eventState(markets);
  const closes = closeLabel(event.end_date, state, Date.now() / 1000);
  const tone = STATE_TONE[state];

  return (
    <Link
      to={`/events/${event.slug}`}
      className="group relative block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <article className="flex h-full flex-col gap-4 rounded-2xl border bg-card p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-foreground/25 group-hover:shadow-[0_18px_36px_-22px_rgba(0,0,0,0.25)]">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          {/* See MarketCard: ACTIVE is the default and marks nothing. */}
          {state === "ACTIVE" ? (
            <span />
          ) : (
            <span className="flex min-w-0 items-center gap-1.5">
              <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", tone.dot)} />
              <span className={cn("truncate", tone.label)}>{state}</span>
            </span>
          )}
          <span className="shrink-0 whitespace-nowrap">
            {closes ? (
              <>
                {closes.prefix ? (
                  <span className="text-foreground/40">{closes.prefix} </span>
                ) : null}
                {closes.value}
              </>
            ) : event.category ? (
              <span className="text-foreground/40">{event.category}</span>
            ) : null}
          </span>
        </div>

        <div className="flex items-start gap-3">
          {event.icon_url ? (
            <img
              src={event.icon_url}
              alt=""
              className="size-10 shrink-0 rounded-md object-cover ring-1 ring-border"
              loading="lazy"
            />
          ) : null}
          <h3 className="line-clamp-2 text-[17px] font-medium leading-[1.25] tracking-tight text-balance">
            {event.title}
          </h3>
        </div>

        <div>
          {previewMarkets.map((m) => (
            <PreviewRow
              key={m.market_id}
              market={m}
              mid={midByMarket.get(m.market_id)}
            />
          ))}
          {extra > 0 ? (
            <div className="pt-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
              + {extra} more outcome{extra === 1 ? "" : "s"}
            </div>
          ) : null}
        </div>

        {vol ? (
          <div className="mt-auto flex items-center gap-1.5 border-t pt-3 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
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
