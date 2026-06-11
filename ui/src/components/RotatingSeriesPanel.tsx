import { useEffect, useMemo, useState } from "react";
import { Orderbook } from "@/components/orders/Orderbook";
import { formatClock, formatCountdown } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RotatingSeries } from "@/lib/rotatingSeries";
import type { Market } from "@/types/market";

const PAST_PREVIEW = 4;

type WindowKind = "live" | "upcoming" | "past";

interface RotatingSeriesPanelProps {
  series: RotatingSeries;
  selectedMarketId: number | null;
  selectedOutcome: string | null;
  onSelectWindow: (marketId: number, outcome: string) => void;
}

/** Ticking wall clock in unix seconds, for the live-window countdown. */
function useNowSec(): number {
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const id = setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return nowSec;
}

function firstOutcome(market: Market): string {
  return market.erc1155_tokens[0]?.[1] ?? "Up";
}

function tokenFor(market: Market, outcome: string | null): string {
  const wanted = outcome ?? firstOutcome(market);
  return (
    market.erc1155_tokens.find(([, label]) => label === wanted)?.[0] ??
    market.erc1155_tokens[0]?.[0] ??
    ""
  );
}

export function RotatingSeriesPanel({
  series,
  selectedMarketId,
  selectedOutcome,
  onSelectWindow,
}: RotatingSeriesPanelProps) {
  const nowSec = useNowSec();
  const { live, upcoming, past, interval } = series;
  const [showAllPast, setShowAllPast] = useState(false);

  const windowOpen = (m: Market): number | null =>
    m.end_date != null ? m.end_date - interval : null;

  const pastShown = showAllPast ? past : past.slice(0, PAST_PREVIEW);
  const hiddenPast = past.length - pastShown.length;
  // `past` is most-recent-first; reverse the shown slice for a left→right
  // chronological timeline ending at the live window.
  const stripPast = useMemo(() => [...pastShown].reverse(), [pastShown]);

  const selected =
    [live, ...upcoming, ...past].find(
      (m): m is Market => m != null && m.market_id === selectedMarketId,
    ) ?? live;

  const kindOf = (m: Market): WindowKind =>
    m === live ? "live" : past.includes(m) ? "past" : "upcoming";

  const liveRemaining =
    live?.end_date != null ? live.end_date - nowSec : null;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          <span
            aria-hidden
            className="size-1.5 animate-pulse-dot rounded-full bg-emerald-500"
          />
          Rotating market · {past.length + (live ? 1 : 0) + upcoming.length}{" "}
          windows
        </span>
        {live && liveRemaining != null && liveRemaining > 0 ? (
          <span className="font-mono text-[10px] uppercase tracking-[0.22em]">
            <span className="text-foreground/40">closes in </span>
            <span className="tabular-nums text-foreground/80">
              {formatCountdown(liveRemaining)}
            </span>
          </span>
        ) : null}
      </div>

      <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
        {hiddenPast > 0 ? (
          <button
            type="button"
            onClick={() => setShowAllPast(true)}
            className="flex shrink-0 items-center rounded-xl border border-dashed border-border px-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
          >
            +{hiddenPast}
          </button>
        ) : null}
        {stripPast.map((m) => (
          <WindowChip
            key={m.market_id}
            market={m}
            openSec={windowOpen(m)}
            kind="past"
            selected={selected?.market_id === m.market_id}
            onSelect={onSelectWindow}
          />
        ))}
        {live ? (
          <WindowChip
            market={live}
            openSec={windowOpen(live)}
            kind="live"
            selected={selected?.market_id === live.market_id}
            onSelect={onSelectWindow}
          />
        ) : null}
        {upcoming.map((m) => (
          <WindowChip
            key={m.market_id}
            market={m}
            openSec={windowOpen(m)}
            kind="upcoming"
            selected={selected?.market_id === m.market_id}
            onSelect={onSelectWindow}
          />
        ))}
      </div>

      {selected ? (
        <div
          key={selected.market_id}
          className="animate-fade-up rounded-2xl border bg-card/40 px-5 py-5"
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                {kindOf(selected) === "live"
                  ? "Live window"
                  : kindOf(selected) === "past"
                    ? "Resolved window"
                    : "Upcoming window"}
              </div>
              <div className="text-sm font-medium tabular-nums">
                {formatClock(windowOpen(selected))} –{" "}
                {formatClock(selected.end_date)}
              </div>
            </div>
            <StatusBadge kind={kindOf(selected)} />
          </div>
          <Orderbook
            tokenId={tokenFor(selected, selectedOutcome)}
            outcome={selectedOutcome ?? firstOutcome(selected)}
          />
        </div>
      ) : null}
    </div>
  );
}

const KIND_LABEL: Record<WindowKind, string> = {
  live: "Live",
  upcoming: "Soon",
  past: "Ended",
};

function WindowChip({
  market,
  openSec,
  kind,
  selected,
  onSelect,
}: {
  market: Market;
  openSec: number | null;
  kind: WindowKind;
  selected: boolean;
  onSelect: (marketId: number, outcome: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(market.market_id, firstOutcome(market))}
      className={cn(
        "flex min-w-[84px] shrink-0 flex-col items-start gap-1.5 rounded-xl border px-3 py-2.5 text-left transition-all",
        selected
          ? "border-foreground/40 bg-foreground/[0.03] shadow-[0_10px_24px_-18px_rgba(0,0,0,0.35)]"
          : "border-border hover:-translate-y-0.5 hover:border-foreground/25",
        kind === "past" && !selected && "opacity-55",
        kind === "live" && "border-emerald-500/40",
      )}
    >
      <span className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
        {kind === "live" ? (
          <span
            aria-hidden
            className="size-1 animate-pulse-dot rounded-full bg-emerald-500"
          />
        ) : null}
        <span
          className={cn(
            kind === "live" && "text-emerald-700 dark:text-emerald-400",
          )}
        >
          {KIND_LABEL[kind]}
        </span>
      </span>
      <span className="text-sm font-semibold tabular-nums leading-none">
        {formatClock(openSec)}
      </span>
    </button>
  );
}

const BADGE_TONE: Record<WindowKind, string> = {
  live: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/20 dark:text-emerald-400",
  upcoming: "bg-sky-500/10 text-sky-700 ring-sky-500/20 dark:text-sky-400",
  past: "bg-muted text-muted-foreground ring-border",
};

function StatusBadge({ kind }: { kind: WindowKind }) {
  return (
    <span
      className={cn(
        "rounded-full px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.18em] ring-1 ring-inset",
        BADGE_TONE[kind],
      )}
    >
      {kind === "live" ? "Trading now" : kind === "past" ? "Closed" : "Pre-open"}
    </span>
  );
}
