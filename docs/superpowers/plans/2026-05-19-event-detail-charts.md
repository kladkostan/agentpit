# Event-Detail Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 24-hour price chart to the top of `/events/:slug`. Single-outcome events show one line; multi-outcome events overlay the top 4 markets by current chance on a single chart with distinct colors and a compact legend.

**Architecture:** Frontend-only. Two new pure utility modules (`chartGeometry`, `eventChartSeries`) — TDD'd — drive two new React components (`MultiSparkline` renderer, `EventChart` orchestrator). The existing `Sparkline` is refactored to consume `chartGeometry.smoothPath` so both single and multi paths use the same math.

**Tech Stack:** React 18, TypeScript (strict), Vite, Tailwind, TanStack Query, Vitest. No new dependencies.

**Reference spec:** [docs/superpowers/specs/2026-05-19-event-detail-charts-design.md](../specs/2026-05-19-event-detail-charts-design.md)

---

## File Structure

```
ui/
└── src/
    ├── lib/
    │   ├── chartGeometry.ts                [new]    smoothPath + projectToViewBox helpers
    │   ├── chartGeometry.test.ts           [new]    Vitest unit tests
    │   ├── eventChartSeries.ts             [new]    pickChartSeries(markets, midByMarket, palette, n)
    │   └── eventChartSeries.test.ts        [new]    Vitest unit tests
    ├── components/
    │   ├── Sparkline.tsx                   [modify] use chartGeometry.smoothPath; remove the inline copy
    │   ├── MultiSparkline.tsx              [new]    pure SVG renderer for N smoothed lines + gridlines + last-point dots
    │   └── EventChart.tsx                  [new]    orchestrator: picks series, fetches sparklines, renders MultiSparkline or empty state
    └── pages/
        └── EventDetailPage.tsx             [modify] mount <EventChart /> between the header and the column layout
```

**Reused without changes:**
- `useSparkline(market_id, outcome)` in `ui/src/api/markets.ts` (already returns `{ points, volume_micro_usd }`)
- `sortMarketsByYesMid` in `ui/src/lib/eventOutcomes.ts`
- `useYesMidMap` already called at the top of `EventDetailPage.tsx`

---

## Task 1: Extract `chartGeometry` from `Sparkline.tsx`

**Files:**
- Create: `ui/src/lib/chartGeometry.ts`
- Create: `ui/src/lib/chartGeometry.test.ts`
- Modify: `ui/src/components/Sparkline.tsx`

Goal: make `smoothPath` and the price→viewBox projection callable from both `Sparkline` and the new `MultiSparkline`. Refactor only — no behavior change for the home page cards.

- [ ] **Step 1a — Write the failing test for `smoothPath`**

Create `ui/src/lib/chartGeometry.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { smoothPath } from "./chartGeometry";

describe("smoothPath", () => {
  it("returns empty string for no points", () => {
    expect(smoothPath([])).toBe("");
  });

  it("returns a single Move command for one point", () => {
    expect(smoothPath([[10, 20]])).toBe("M 10 20");
  });

  it("starts at the first point for multi-point input", () => {
    const path = smoothPath([
      [0, 50],
      [10, 40],
      [20, 30],
    ]);
    expect(path.startsWith("M 0 50")).toBe(true);
  });

  it("emits one cubic segment per gap between adjacent samples", () => {
    const path = smoothPath([
      [0, 0],
      [10, 10],
      [20, 0],
    ]);
    // M + 2 cubic segments → exactly two "C" commands
    expect(path.match(/C/g)?.length).toBe(2);
  });
});
```

- [ ] **Step 1b — Run the test and confirm it fails**

Run: `cd ui && yarn test --run lib/chartGeometry`
Expected: ImportError / Module not found — `chartGeometry` doesn't exist yet.

- [ ] **Step 1c — Create the module**

Create `ui/src/lib/chartGeometry.ts` with:

```ts
/** A point in the chart's local coordinate space (post-projection). */
export type ChartCoord = readonly [x: number, y: number];

/** A raw price sample as returned by `/sparkline`. */
export interface SparklineSample {
  /** Unix seconds. */
  t: number;
  /** Price in micro-USDC (0–1_000_000). */
  p: number;
}

/**
 * Catmull–Rom → Bézier smoothing. Produces a soft path through every
 * sample. No external dependency.
 */
export function smoothPath(coords: ReadonlyArray<ChartCoord>): string {
  if (coords.length === 0) return "";
  if (coords.length === 1) {
    const [x, y] = coords[0]!;
    return `M ${x} ${y}`;
  }
  const tension = 0.5;
  let d = `M ${coords[0]![0]} ${coords[0]![1]}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[i - 1] ?? coords[i]!;
    const p1 = coords[i]!;
    const p2 = coords[i + 1]!;
    const p3 = coords[i + 2] ?? p2;
    const cp1x = p1[0] + ((p2[0] - p0[0]) / 6) * tension;
    const cp1y = p1[1] + ((p2[1] - p0[1]) / 6) * tension;
    const cp2x = p2[0] - ((p3[0] - p1[0]) / 6) * tension;
    const cp2y = p2[1] - ((p3[1] - p1[1]) / 6) * tension;
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2[0]} ${p2[1]}`;
  }
  return d;
}
```

- [ ] **Step 1d — Run the test and confirm it passes**

Run: `cd ui && yarn test --run lib/chartGeometry`
Expected: 4 passing.

- [ ] **Step 1e — Write the failing test for `projectToViewBox`**

Append to `ui/src/lib/chartGeometry.test.ts`:

```ts
import { projectToViewBox } from "./chartGeometry";

describe("projectToViewBox", () => {
  const dims = { width: 100, height: 50, padX: 0, padY: 0 };

  it("returns an empty array when given no samples", () => {
    expect(projectToViewBox([], dims)).toEqual([]);
  });

  it("places a single sample at the right edge, vertically centered on its value", () => {
    const out = projectToViewBox(
      [{ t: 0, p: 500_000 }],
      dims,
    );
    expect(out).toEqual([[100, 25]]);
  });

  it("spaces samples evenly across the X axis", () => {
    const out = projectToViewBox(
      [
        { t: 0, p: 0 },
        { t: 1, p: 500_000 },
        { t: 2, p: 1_000_000 },
      ],
      dims,
    );
    expect(out.map(([x]) => x)).toEqual([0, 50, 100]);
  });

  it("maps price 1_000_000 to y=0 (top) and price 0 to y=height (bottom)", () => {
    const out = projectToViewBox(
      [
        { t: 0, p: 0 },
        { t: 1, p: 1_000_000 },
      ],
      dims,
    );
    expect(out[0]![1]).toBe(50);
    expect(out[1]![1]).toBe(0);
  });

  it("clamps prices outside [0, 1_000_000] to the chart edges", () => {
    const out = projectToViewBox(
      [
        { t: 0, p: -100 },
        { t: 1, p: 2_000_000 },
      ],
      dims,
    );
    expect(out[0]![1]).toBe(50);
    expect(out[1]![1]).toBe(0);
  });

  it("respects horizontal and vertical padding", () => {
    const out = projectToViewBox(
      [
        { t: 0, p: 0 },
        { t: 1, p: 1_000_000 },
      ],
      { width: 100, height: 50, padX: 5, padY: 2 },
    );
    expect(out[0]).toEqual([5, 48]);
    expect(out[1]).toEqual([95, 2]);
  });
});
```

- [ ] **Step 1f — Run the test and confirm it fails**

Run: `cd ui && yarn test --run lib/chartGeometry`
Expected: 4 passing, 6 failing — `projectToViewBox is not a function`.

- [ ] **Step 1g — Implement `projectToViewBox`**

Append to `ui/src/lib/chartGeometry.ts`:

```ts
export interface ProjectionDims {
  width: number;
  height: number;
  padX?: number;
  padY?: number;
}

/** Project sparkline samples into chart-local SVG coords.
 *
 *  Y-axis is fixed: price = 1_000_000 (i.e. 100%) → top edge (y=padY);
 *  price = 0 → bottom edge (y=height-padY). Prices are clamped — see the
 *  clamp test for rationale (defensive guard against bad upstream data).
 *
 *  X-axis is by sample index, not by timestamp — sparse trade streams stay
 *  comfortably spaced rather than clumping near recent activity.
 */
export function projectToViewBox(
  samples: ReadonlyArray<SparklineSample>,
  { width, height, padX = 0, padY = 0 }: ProjectionDims,
): ChartCoord[] {
  if (samples.length === 0) return [];
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;
  const lastIdx = Math.max(1, samples.length - 1);
  const PRICE_MAX = 1_000_000;
  return samples.map((s, i): ChartCoord => {
    const xRatio = samples.length === 1 ? 1 : i / lastIdx;
    const clampedP = Math.max(0, Math.min(PRICE_MAX, s.p));
    const yRatio = clampedP / PRICE_MAX;
    return [padX + xRatio * innerW, padY + innerH - yRatio * innerH];
  });
}
```

- [ ] **Step 1h — Run the test and confirm it passes**

Run: `cd ui && yarn test --run lib/chartGeometry`
Expected: 10 passing.

- [ ] **Step 1i — Refactor `Sparkline.tsx` to use `chartGeometry`**

Open `ui/src/components/Sparkline.tsx`. Replace the inline `smoothPath` function (lines defining it) and the inline projection inside the `geometry` useMemo with calls to the new module.

Concretely, at the top of the file:

```ts
import { projectToViewBox, smoothPath } from "@/lib/chartGeometry";
```

Then delete the local `smoothPath` definition and replace the projection block inside `useMemo`. The new `useMemo` body becomes:

```ts
const geometry = useMemo(() => {
  if (points.length === 0) return null;
  const coords = projectToViewBox(points, {
    width,
    height,
    padX: 1,
    padY: 4,
  });
  const path = smoothPath(coords);
  const last = coords[coords.length - 1]!;
  const first = coords[0]!;
  const area =
    path + ` L ${last[0]} ${height} L ${first[0]} ${height} Z`;
  return { coords, path, area };
}, [points, width, height]);
```

- [ ] **Step 1j — Run the existing test suite to confirm no regression**

Run: `cd ui && yarn test --run && yarn typecheck`
Expected: all existing tests still pass; typecheck clean.

- [ ] **Step 1k — Commit**

```bash
git add ui/src/lib/chartGeometry.ts ui/src/lib/chartGeometry.test.ts ui/src/components/Sparkline.tsx
git commit -m "ui: extract chartGeometry helpers (smoothPath + projection)"
```

---

## Task 2: `eventChartSeries.pickChartSeries`

**Files:**
- Create: `ui/src/lib/eventChartSeries.ts`
- Create: `ui/src/lib/eventChartSeries.test.ts`

Goal: pure function that, given the event's markets + a YES-mid map + a color palette, returns the list of series the chart should render. Top N by current chance.

- [ ] **Step 2a — Write the failing test**

Create `ui/src/lib/eventChartSeries.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Market } from "@/types/market";
import { pickChartSeries } from "./eventChartSeries";

function fakeMarket(id: number, label: string): Market {
  // Minimal cast — only the fields pickChartSeries reads matter.
  return {
    market_id: id,
    question: label,
    slug: label,
    description: "",
    erc1155_tokens: [["t-y", "Yes"], ["t-n", "No"]],
    start_date: null,
    end_date: null,
    market_state: "ACTIVE",
    resolved_outcome: null,
    polymarket_id: null,
    condition_id: "0x" + "0".repeat(64),
    event_id: null,
    outcome_label: label,
    icon_url: null,
  } as Market;
}

const PALETTE = ["#1", "#2", "#3", "#4"] as const;

describe("pickChartSeries", () => {
  it("returns an empty array when given no markets", () => {
    expect(pickChartSeries([], new Map(), PALETTE, 4)).toEqual([]);
  });

  it("orders markets by descending YES mid and assigns palette by rank", () => {
    const a = fakeMarket(1, "Alice");
    const b = fakeMarket(2, "Bob");
    const c = fakeMarket(3, "Carol");
    const mid = new Map<number, number>([
      [1, 0.10],
      [2, 0.50],
      [3, 0.25],
    ]);
    const series = pickChartSeries([a, b, c], mid, PALETTE, 4);
    expect(series.map((s) => s.market.market_id)).toEqual([2, 3, 1]);
    expect(series.map((s) => s.color)).toEqual(["#1", "#2", "#3"]);
  });

  it("slices to n and never wraps the palette", () => {
    const markets = [
      fakeMarket(1, "a"),
      fakeMarket(2, "b"),
      fakeMarket(3, "c"),
      fakeMarket(4, "d"),
      fakeMarket(5, "e"),
    ];
    const mid = new Map<number, number>([
      [1, 0.9],
      [2, 0.7],
      [3, 0.5],
      [4, 0.3],
      [5, 0.1],
    ]);
    const series = pickChartSeries(markets, mid, PALETTE, 4);
    expect(series).toHaveLength(4);
    expect(series.map((s) => s.market.market_id)).toEqual([1, 2, 3, 4]);
    expect(series.map((s) => s.color)).toEqual(["#1", "#2", "#3", "#4"]);
  });

  it("places markets without a known mid at the tail", () => {
    const a = fakeMarket(1, "Alice");
    const b = fakeMarket(2, "Bob");
    const mid = new Map<number, number>([[1, 0.5]]);
    const series = pickChartSeries([a, b], mid, PALETTE, 4);
    expect(series.map((s) => s.market.market_id)).toEqual([1, 2]);
  });

  it("uses the outcome_label or question as the legend label", () => {
    const m = fakeMarket(1, "France?");
    m.outcome_label = "France";
    const series = pickChartSeries(
      [m],
      new Map([[1, 0.5]]),
      PALETTE,
      4,
    );
    expect(series[0]!.label).toBe("France");
  });
});
```

- [ ] **Step 2b — Run the test and confirm it fails**

Run: `cd ui && yarn test --run lib/eventChartSeries`
Expected: Module not found.

- [ ] **Step 2c — Implement the function**

Create `ui/src/lib/eventChartSeries.ts`:

```ts
import { sortMarketsByYesMid } from "@/lib/eventOutcomes";
import type { Market } from "@/types/market";

export interface ChartSeries {
  market: Market;
  label: string;
  color: string;
}

/**
 * Pick the top-N markets to render on the event chart, ordered by
 * descending current YES mid. Each picked market gets a palette color
 * assigned by rank — #1 → palette[0], #2 → palette[1], and so on. The
 * palette is never wrapped; if there are more markets than colors the
 * tail is dropped.
 */
export function pickChartSeries(
  markets: ReadonlyArray<Market>,
  midByMarket: ReadonlyMap<number, number>,
  palette: ReadonlyArray<string>,
  n: number,
): ChartSeries[] {
  const ranked = sortMarketsByYesMid(markets, midByMarket);
  const top = ranked.slice(0, Math.min(n, palette.length));
  return top.map((market, i) => ({
    market,
    label: market.outcome_label ?? market.question,
    color: palette[i]!,
  }));
}
```

- [ ] **Step 2d — Run the test and confirm it passes**

Run: `cd ui && yarn test --run lib/eventChartSeries`
Expected: 5 passing.

- [ ] **Step 2e — Commit**

```bash
git add ui/src/lib/eventChartSeries.ts ui/src/lib/eventChartSeries.test.ts
git commit -m "ui: add pickChartSeries helper for event chart series picking"
```

---

## Task 3: `MultiSparkline` renderer

**Files:**
- Create: `ui/src/components/MultiSparkline.tsx`

Goal: pure presentational component. Takes a list of series (each with a color and points) and renders gridlines + smoothed paths + last-point dots inside a fixed-aspect SVG.

- [ ] **Step 3a — Create the component**

Create `ui/src/components/MultiSparkline.tsx`:

```tsx
import { useMemo } from "react";
import { projectToViewBox, smoothPath } from "@/lib/chartGeometry";
import type { SparklineSample } from "@/lib/chartGeometry";
import { cn } from "@/lib/utils";

export interface MultiSparklineSeries {
  id: string | number;
  color: string;
  points: ReadonlyArray<SparklineSample>;
}

interface MultiSparklineProps {
  series: ReadonlyArray<MultiSparklineSeries>;
  /** Logical viewBox width — actual rendered width is controlled by CSS. */
  width?: number;
  height?: number;
  className?: string;
}

const GRIDLINE_Y_PCT = [25, 50, 75] as const;

export function MultiSparkline({
  series,
  width = 600,
  height = 180,
  className,
}: MultiSparklineProps) {
  const projected = useMemo(
    () =>
      series.map((s) => ({
        ...s,
        coords: projectToViewBox(s.points, {
          width,
          height,
          padX: 4,
          padY: 6,
        }),
      })),
    [series, width, height],
  );

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("block h-[180px] w-full overflow-visible", className)}
      aria-hidden
    >
      {/* Gridlines */}
      {GRIDLINE_Y_PCT.map((pct) => {
        const y = height - (pct / 100) * height;
        return (
          <line
            key={pct}
            x1={0}
            x2={width}
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeWidth={1}
            className="text-foreground/[0.04]"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Series paths + last-point dots */}
      {projected.map((s) => {
        if (s.coords.length === 0) return null;
        const last = s.coords[s.coords.length - 1]!;
        const d = smoothPath(s.coords);
        return (
          <g key={s.id}>
            <path
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={last[0]}
              cy={last[1]}
              r={2.5}
              fill={s.color}
              stroke="hsl(var(--background))"
              strokeWidth={1.25}
            />
          </g>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 3b — Verify it typechecks**

Run: `cd ui && yarn typecheck`
Expected: no errors.

- [ ] **Step 3c — Commit**

```bash
git add ui/src/components/MultiSparkline.tsx
git commit -m "ui: add MultiSparkline renderer for multi-series sparkline"
```

---

## Task 4: `EventChart` orchestrator

**Files:**
- Create: `ui/src/components/EventChart.tsx`

Goal: orchestrator that picks the series, fans out `useSparkline` queries, renders the chart card with header + legend + chart or empty state.

- [ ] **Step 4a — Create the component**

Create `ui/src/components/EventChart.tsx`:

```tsx
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
```

- [ ] **Step 4b — Verify it typechecks**

Run: `cd ui && yarn typecheck`
Expected: no errors.

- [ ] **Step 4c — Commit**

```bash
git add ui/src/components/EventChart.tsx
git commit -m "ui: add EventChart orchestrator with legend and empty state"
```

---

## Task 5: Mount `EventChart` in `EventDetailPage`

**Files:**
- Modify: `ui/src/pages/EventDetailPage.tsx`

Goal: render `<EventChart />` between the event header and the column layout.

- [ ] **Step 5a — Import `EventChart`**

In `ui/src/pages/EventDetailPage.tsx`, add to the import block (alongside other component imports):

```ts
import { EventChart } from "@/components/EventChart";
```

- [ ] **Step 5b — Mount it between the header and the columns**

Find the `</header>` line in the render output. Immediately after it (still inside the outer `<section>`), insert:

```tsx
      <EventChart markets={markets} midByMarket={midByMarket} />
```

The resulting structure should read:

```tsx
      <header className="space-y-5 border-b pb-8">
        {/* …existing header… */}
      </header>

      <EventChart markets={markets} midByMarket={midByMarket} />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* …single-market vs leaderboard branch… */}
      </div>
```

- [ ] **Step 5c — Verify it typechecks + tests pass + lint clean**

Run: `cd ui && yarn typecheck && yarn lint && yarn test --run`
Expected: all green.

- [ ] **Step 5d — Commit**

```bash
git add ui/src/pages/EventDetailPage.tsx
git commit -m "ui: mount EventChart on event detail page"
```

---

## Task 6: Visual verification with Playwright

**Files:** none modified.

Goal: confirm the chart renders correctly for single-market and multi-market events, and that the empty state appears when no trade history exists.

- [ ] **Step 6a — Start the dev server in the background**

Run: `cd ui && yarn dev` (in background)
Wait until `http://localhost:5173` responds with 200.

- [ ] **Step 6b — Single-market event detail page**

Navigate to `http://localhost:5173/events/xi-jinping-out-before-2027` and screenshot.

Expected: chart section visible between header and orderbook. Likely shows the empty state ("No price history yet") because the local DB usually has no trade history on this market yet. If a real trade has occurred, expect one emerald line.

- [ ] **Step 6c — Multi-market event detail page**

Navigate to `http://localhost:5173/events/democratic-presidential-nominee-2028` and screenshot.

Expected: chart section visible above the leaderboard. Legend shows up to 4 outcomes in distinct colors (emerald, sky, amber, rose). Chart area shows the empty state when there's no trade history.

- [ ] **Step 6d — Stop the dev server**

Stop the background `yarn dev` task.

- [ ] **Step 6e — Clean up screenshot files**

Run: `rm -f *.png` in the project root.

- [ ] **Step 6f — Final commit (no-op or visual fix)**

If the visual check uncovered a layout issue, fix it now in a small commit referencing the bug. Otherwise no commit needed for Task 6.

---

## Self-review checklist (run before handing off)

1. **Spec coverage** — every section of the spec maps to a task:
   - Goals → Tasks 1-5
   - Single + multi-market behavior → Tasks 2, 4, 5
   - Visual + placement → Tasks 3, 4, 5
   - Series selection → Task 2
   - Empty state → Task 4 (`hasData` branch)
   - Data flow + edge cases (no points, fewer than 4 markets, etc.) → Tasks 2, 4
   - Testing → Tasks 1, 2 (unit tests) and Task 6 (Playwright)
2. **Placeholder scan** — every step contains the literal code or command an engineer needs. No "TBD", no "implement later".
3. **Type consistency** — `MultiSparklineSeries.id` is `string | number` (Task 3); `pickChartSeries` returns `market_id: number` (Task 2). `EventChart` uses `market.market_id` as the id (Task 4). ✓
4. **Color values** — RGB strings in `EventChart` palette match the spec's Tailwind hex values (`#10b981` = `rgb(16 185 129)`, etc.). ✓
