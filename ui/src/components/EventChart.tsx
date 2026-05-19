import { useQueries } from "@tanstack/react-query";
import { getSparkline } from "@/api/markets";
import { MultiSparkline } from "@/components/MultiSparkline";
import type { MultiSparklineSeries } from "@/components/MultiSparkline";
import { pickChartSeries } from "@/lib/eventChartSeries";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/market";

interface EventChartProps {
  markets: ReadonlyArray<Market>;
  midByMarket: ReadonlyMap<number, number>;
}

/** Palette by rank — #1 emerald, #2 sky, #3 amber, #4 rose. */
const PALETTE = [
  "rgb(16 185 129)",   // emerald-500
  "rgb(14 165 233)",   // sky-500
  "rgb(245 158 11)",   // amber-500
  "rgb(244 63 94)",    // rose-500
] as const;

export function EventChart({ markets, midByMarket }: EventChartProps) {
  const picked = pickChartSeries(markets, midByMarket, PALETTE, 4);

  // Fan-out one sparkline query per picked market. Same query key shape as
  // useSparkline so cache hits are shared with anything else asking for the
  // same (market_id, outcome) pair.
  const queries = useQueries({
    queries: picked.map((s) => {
      const outcome = s.market.erc1155_tokens[0]?.[1] ?? "Yes";
      return {
        queryKey: ["sparkline", s.market.market_id, outcome],
        queryFn: () => getSparkline(s.market.market_id, outcome),
        staleTime: 30_000,
        refetchInterval: 60_000,
        refetchOnWindowFocus: false,
        refetchIntervalInBackground: false,
      };
    }),
  });

  const series: MultiSparklineSeries[] = picked.map((s, i) => ({
    id: s.market.market_id,
    color: s.color,
    points: queries[i]?.data?.points ?? [],
  }));

  const totalPoints = series.reduce((n, s) => n + s.points.length, 0);
  const hasData = totalPoints >= 2;

  return (
    <section className="rounded-2xl border bg-card/40 px-5 py-5">
      <header className="mb-4 flex items-baseline justify-between gap-4">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          24h trend
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
        <MultiSparkline series={series} />
      ) : (
        <div
          className={cn(
            "flex h-[180px] items-center justify-center rounded-xl",
            "border border-dashed border-border/60 bg-foreground/[0.015]",
          )}
        >
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground/70">
            No price history yet
          </p>
        </div>
      )}
    </section>
  );
}
