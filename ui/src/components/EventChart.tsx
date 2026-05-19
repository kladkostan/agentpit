import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { getSparkline } from "@/api/markets";
import { GRIDLINE_Y_PCT, MultiSparkline, PAD_Y } from "@/components/MultiSparkline";
import type { MultiSparklineSeries } from "@/components/MultiSparkline";
import { CHART_PALETTE } from "@/lib/chartPalette";
import { pickChartSeries } from "@/lib/eventChartSeries";
import { formatShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/market";

interface EventChartProps {
  markets: ReadonlyArray<Market>;
  midByMarket: ReadonlyMap<number, number>;
}

/** Y-axis labels read top → bottom, with the interior gridlines flanked by
 *  the 0 % / 100 % chart edges. Derived from the gridlines so the two stay
 *  in sync if `GRIDLINE_Y_PCT` ever changes. */
const Y_AXIS_LABELS = [
  "100%",
  ...[...GRIDLINE_Y_PCT].reverse().map((p) => `${p}%`),
  "0%",
];

/** How many time markers to spread across the X axis. */
const X_AXIS_TICKS = 5;
/** Window of price history shown on the event detail chart. */
const WINDOW_HOURS = 30 * 24;
/** Chart canvas height in viewBox + CSS pixels. */
const CHART_HEIGHT = 260;

function pickXAxisLabels(series: ReadonlyArray<MultiSparklineSeries>): string[] {
  // Pick the time range that covers every series — if some markets started
  // trading earlier than others, the axis should span the union.
  let minT = Number.POSITIVE_INFINITY;
  let maxT = Number.NEGATIVE_INFINITY;
  for (const s of series) {
    for (const p of s.points) {
      if (p.t < minT) minT = p.t;
      if (p.t > maxT) maxT = p.t;
    }
  }
  if (!Number.isFinite(minT) || !Number.isFinite(maxT) || minT === maxT) {
    return [];
  }
  return Array.from({ length: X_AXIS_TICKS }, (_, i) => {
    const t = minT + ((maxT - minT) * i) / (X_AXIS_TICKS - 1);
    return formatShortDate(t) ?? "";
  });
}

export function EventChart({ markets, midByMarket }: EventChartProps) {
  const picked = useMemo(
    () => pickChartSeries(markets, midByMarket, CHART_PALETTE, 4),
    [markets, midByMarket],
  );

  const queries = useQueries({
    queries: picked.map((s) => {
      const outcome = s.market.erc1155_tokens[0]?.[1] ?? "Yes";
      return {
        queryKey: ["sparkline", s.market.market_id, outcome, WINDOW_HOURS],
        queryFn: () => getSparkline(s.market.market_id, outcome, WINDOW_HOURS),
        staleTime: 30_000,
        refetchInterval: 60_000,
        refetchOnWindowFocus: false,
        refetchIntervalInBackground: false,
      };
    }),
  });

  // `useQueries` returns a fresh array per render, so derive a stable
  // `data` slice for the memo dep — `series` and `xLabels` only need to
  // recompute when the actual points payload changes.
  const queryData = queries.map((q) => q.data);
  const series = useMemo<MultiSparklineSeries[]>(
    () =>
      picked.map((s, i) => ({
        id: s.market.market_id,
        color: s.color,
        points: queryData[i]?.points ?? [],
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [picked, ...queryData],
  );

  const totalPoints = series.reduce((n, s) => n + s.points.length, 0);
  const hasData = totalPoints >= 2;
  const xLabels = useMemo(
    () => (hasData ? pickXAxisLabels(series) : []),
    [hasData, series],
  );

  return (
    <section className="rounded-2xl border bg-card/40 px-5 py-5">
      <header className="mb-4 flex items-baseline justify-between gap-4">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          30d trend
        </span>
        {hasData ? (
          <ol className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-[11px]">
            {picked.map((s, i) => {
              const mid = midByMarket.get(s.market.market_id);
              const cents = mid !== undefined ? Math.round(mid * 100) : null;
              return (
                <li
                  key={s.market.market_id}
                  className="flex items-center gap-1.5"
                  style={{ color: s.color }}
                >
                  <span
                    aria-hidden
                    className="size-1.5 rounded-full"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="text-foreground/80">{s.label}</span>
                  {cents !== null ? (
                    <span className="tabular-nums text-muted-foreground">
                      {cents}%
                    </span>
                  ) : null}
                  {i < picked.length - 1 ? (
                    <span aria-hidden className="text-foreground/15">·</span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </header>

      {hasData ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-stretch gap-3">
            <ol
              className="flex flex-col justify-between font-mono text-[10px] tabular-nums text-muted-foreground"
              style={{ paddingTop: PAD_Y, paddingBottom: PAD_Y }}
              aria-hidden
            >
              {Y_AXIS_LABELS.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ol>
            <div className="flex-1">
              <MultiSparkline series={series} height={CHART_HEIGHT} />
            </div>
          </div>
          <ol
            className="grid text-center font-mono text-[10px] tabular-nums text-muted-foreground"
            style={{ gridTemplateColumns: `repeat(${xLabels.length}, 1fr)` }}
            aria-hidden
          >
            {xLabels.map((l, i) => (
              <li
                key={i}
                className={cn(
                  i === 0 && "text-left",
                  i === xLabels.length - 1 && "text-right",
                )}
              >
                {l}
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <div
          className={cn(
            "flex items-center justify-center rounded-xl",
            "border border-dashed border-border/60 bg-foreground/[0.015]",
          )}
          style={{ height: CHART_HEIGHT }}
        >
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground/70">
            No price history yet
          </p>
        </div>
      )}
    </section>
  );
}
