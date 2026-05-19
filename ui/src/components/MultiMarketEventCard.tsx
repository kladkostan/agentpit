import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useYesMidMap } from "@/lib/useYesMid";
import { sortMarketsByYesMid } from "@/lib/eventOutcomes";
import { formatShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Event } from "@/types/event";
import type { Market } from "@/types/market";

interface MultiMarketEventCardProps {
  event: Event;
  markets: Market[];
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
  const pct = mid !== undefined ? Math.round(mid * 100) : null;
  const label = market.outcome_label ?? market.question;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <OutcomeIcon market={market} />
      <span className="flex-1 truncate text-sm">{label}</span>
      <span
        className={cn(
          "font-display text-lg leading-none tabular-nums",
          pct === null && "text-muted-foreground/40",
        )}
      >
        {pct ?? "—"}
        <span className="ml-0.5 text-xs opacity-60">%</span>
      </span>
    </div>
  );
}

export function MultiMarketEventCard({
  event,
  markets,
}: MultiMarketEventCardProps) {
  const midByMarket = useYesMidMap(markets);
  const ranked = useMemo(
    () => sortMarketsByYesMid(markets, midByMarket),
    [markets, midByMarket],
  );
  const previewMarkets = ranked.slice(0, PREVIEW_COUNT);
  const extra = ranked.length - previewMarkets.length;
  const closes = formatShortDate(event.end_date);

  return (
    <Link
      to={`/events/${event.slug}`}
      className="group relative block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <article className="flex h-full flex-col gap-4 rounded-2xl border bg-card p-5 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:border-foreground/25 group-hover:shadow-[0_18px_36px_-22px_rgba(0,0,0,0.25)]">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="size-1.5 rounded-full bg-foreground/30" />
            Event · {markets.length} outcomes
          </span>
          <span>
            {closes ? (
              <>
                <span className="text-foreground/40">closes</span> {closes}
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
      </article>
    </Link>
  );
}
