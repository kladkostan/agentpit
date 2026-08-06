import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { getPricesHistory } from "@/api/markets";
import { MultiSparkline, PAD_Y } from "@/components/MultiSparkline";
import type {
  MultiSparklineHoverState,
  MultiSparklineSeries,
} from "@/components/MultiSparkline";
import { niceChartScale } from "@/lib/chartGeometry";
import { CHART_PALETTE } from "@/lib/chartPalette";
import { carryLastPriceForward, pickChartSeries } from "@/lib/eventChartSeries";
import { formatClock, formatShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/market";

interface EventChartProps {
  markets: ReadonlyArray<Market>;
  midByMarket: ReadonlyMap<number, number>;
}

/** Format a domain fraction (0–1) as an axis label, dropping a trailing
 *  ".0" so clean steps read as "25%" rather than "25.0%". */
function formatAxisPct(fraction: number): string {
  const pct = Math.round(fraction * 1000) / 10;
  return `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`;
}

function formatLegendPct(fraction: number): string {
  const pct = Math.round(fraction * 1000) / 10;
  return Number.isInteger(pct) ? `${pct}` : pct.toFixed(1);
}

/** Prices-history window for the event trend chart: "1m" ≈ 720h (30 days),
 *  matching the "30-day trend" header. */
const CHART_INTERVAL = "1m";
/** How many time markers to spread across the X axis. */
const X_AXIS_TICKS = 5;
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
  const [hover, setHover] = useState<MultiSparklineHoverState | null>(null);

  const picked = useMemo(
    () => pickChartSeries(markets, midByMarket, CHART_PALETTE, 4),
    [markets, midByMarket],
  );

  const queries = useQueries({
    queries: picked.map((s) => {
      const tokenId = s.market.erc1155_tokens[0]?.[0] ?? "";
      // The event chart shows a 30-day trend, so request the "1m" (≈720h)
      // window; the interval is part of the key to avoid colliding with the
      // 1d cache entry used by MarketCard.
      return {
        queryKey: ["prices-history", tokenId, CHART_INTERVAL],
        queryFn: () => getPricesHistory(tokenId, CHART_INTERVAL),
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
    () => {
      // A price holds until the next trade, so every line runs to today. A
      // market that traded once would otherwise be a single coordinate, which
      // draws nothing at all.
      const now = Math.floor(Date.now() / 1000);
      return picked.map((s, i) => ({
        id: s.market.market_id,
        color: s.color,
        label: s.label,
        points: carryLastPriceForward(queryData[i]?.history ?? [], now),
      }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [picked, ...queryData],
  );

  // An outcome with no trades draws no line. Listing it anyway sends the
  // reader hunting for a colour that is not on the chart.
  const traded = useMemo(
    () => picked.filter((_, i) => (series[i]?.points.length ?? 0) > 0),
    [picked, series],
  );

  const totalPoints = series.reduce((n, s) => n + s.points.length, 0);
  const hasData = totalPoints >= 2;
  const xLabels = useMemo(
    () => (hasData ? pickXAxisLabels(series) : []),
    [hasData, series],
  );

  // Zoom the Y axis onto the data: find the peak probability across every
  // series and snap it up to a clean round bound (e.g. a 0.227 peak → a
  // 0–0.25 window) so low-probability outcomes aren't squashed against the floor.
  const scale = useMemo(() => {
    let peak = 0;
    for (const s of series) {
      for (const p of s.points) if (p.p > peak) peak = p.p;
    }
    return niceChartScale(peak);
  }, [series]);

  // Domain top as probability fraction [0, 1], interior gridlines + top→bottom
  // axis labels, all derived from the same ticks so they never drift apart.
  const maxP = scale.max;
  const gridRatios = scale.ticks
    .slice(1, -1)
    .map((t) => t / scale.max);
  const yLabels = [...scale.ticks].reverse().map(formatAxisPct);

  const hoverPctBySeriesId = useMemo(() => {
    if (!hover) return new Map<number, number>();
    return new Map(
      hover.points
        .map((p) => [Number(p.id), p.sample.p] as const)
        .filter(([id]) => Number.isFinite(id)),
    );
  }, [hover]);

  const hoverTimeLabel = useMemo(() => {
    if (!hover || hover.points.length === 0) return null;
    const firstTs = hover.points[0]!.sample.t;
    const date = formatShortDate(firstTs);
    const clock = formatClock(firstTs);
    if (!date || !clock) return null;
    return `${date}, ${clock}`;
  }, [hover]);

  return (
    <section className="rounded-2xl border bg-card/40 px-5 py-5">
      <header className="mb-4 flex items-baseline justify-between gap-4">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          {hoverTimeLabel ?? "30d trend"}
        </span>
        {hasData ? (
          <ol className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-[11px]">
            {traded.map((s, i) => {
              const hoverPct = hoverPctBySeriesId.get(s.market.market_id);
              const mid = midByMarket.get(s.market.market_id);
              const cents =
                hoverPct !== undefined
                  ? formatLegendPct(hoverPct)
                  : mid !== undefined
                    ? String(Math.round(mid * 100))
                    : null;
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
                  {i < traded.length - 1 ? (
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
              {yLabels.map((l, i) => (
                <li key={`${l}-${i}`}>{l}</li>
              ))}
            </ol>
            <div className="flex-1">
              <MultiSparkline
                series={series}
                height={CHART_HEIGHT}
                maxP={maxP}
                gridRatios={gridRatios}
                onHoverChange={setHover}
              />
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
