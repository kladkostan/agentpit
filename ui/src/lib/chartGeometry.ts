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

/** Y-axis projection mode.
 *
 *  - `"fixed"` (default) — price 0 maps to the bottom, 1_000_000 to the top.
 *    Use when multiple charts need directly-comparable axes (e.g. the
 *    multi-line chart on the event detail page).
 *  - `"relative"` — the input's own min/max stretches across the full
 *    height. Use when a single sparkline should look dynamic regardless
 *    of where the price sits in [0, 1] (e.g. home-page market cards).
 *    Constant-price series collapse to the vertical center.
 */
export type ScaleMode = "fixed" | "relative";

export interface ProjectionDims {
  width: number;
  height: number;
  padX?: number;
  padY?: number;
  scaleMode?: ScaleMode;
  /** Upper bound of the fixed-mode domain, in micro-USDC. Defaults to
   *  1_000_000 (a full 0–100% axis). Pass a tighter value (see
   *  {@link niceChartScale}) to zoom the chart onto low-probability data.
   *  Ignored in `"relative"` mode. */
  fixedMax?: number;
}

/** Round `x` (> 0) up to the nearest "nice" number — one of
 *  1, 2, 2.5, 5 or 10 times a power of ten. Used to pick axis step sizes
 *  that read cleanly (5%, 20%, …) rather than arbitrary fractions. */
function ceilToNice(x: number): number {
  const exp = Math.floor(Math.log10(x));
  const base = 10 ** exp;
  const f = x / base; // in [1, 10)
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * base;
}

/** Result of {@link niceChartScale}: a focused vertical domain plus the
 *  evenly-spaced tick fractions (including the 0 floor and the `max` top)
 *  to label and draw gridlines at. */
export interface ChartScale {
  /** Top of the domain as a price fraction in (0, 1]. */
  max: number;
  /** Ascending tick fractions from 0 to `max`, evenly spaced. */
  ticks: number[];
}

const FULL_SCALE: ChartScale = { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] };
const TARGET_INTERVALS = 5;

/** Pick a focused vertical domain that snaps the data's peak up to a clean
 *  round bound, keeping the floor anchored at 0.
 *
 *  `maxFraction` is the largest price in the dataset as a fraction in
 *  [0, 1]. A range topping out at 0.227 (22.7%) returns a 0–25% window with
 *  ticks every 5%, instead of wasting three-quarters of the chart on the
 *  empty 25–100% band. Degenerate input (≤ 0 or non-finite) falls back to a
 *  full 0–100% axis. */
export function niceChartScale(maxFraction: number): ChartScale {
  if (!Number.isFinite(maxFraction) || maxFraction <= 0) return FULL_SCALE;

  const maxPct = Math.min(100, maxFraction * 100);
  const step = ceilToNice(maxPct / TARGET_INTERVALS);
  const ceilPct = Math.min(100, Math.ceil(maxPct / step) * step);
  const count = Math.round(ceilPct / step);

  const ticks = Array.from({ length: count + 1 }, (_, i) =>
    Math.min(i * step, ceilPct) / 100,
  );
  return { max: ceilPct / 100, ticks };
}

/** Project sparkline samples into chart-local SVG coords.
 *
 *  Y-axis convention: higher price → higher in the chart (smaller y).
 *  In `"fixed"` mode the axis spans 0 → 1_000_000 (i.e. 0% → 100%) so
 *  multiple charts have directly-comparable elevations. In `"relative"`
 *  mode the input's own min/max stretches across the full height.
 *
 *  Out-of-range prices in fixed mode are clamped to the chart edges to
 *  defend against bad upstream data.
 *
 *  X-axis is by sample index, not by timestamp — sparse trade streams stay
 *  comfortably spaced rather than clumping near recent activity.
 */
export function projectToViewBox(
  samples: ReadonlyArray<SparklineSample>,
  {
    width,
    height,
    padX = 0,
    padY = 0,
    scaleMode = "fixed",
    fixedMax = 1_000_000,
  }: ProjectionDims,
): ChartCoord[] {
  if (samples.length === 0) return [];
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;
  const lastIdx = Math.max(1, samples.length - 1);

  let minP: number;
  let range: number;
  if (scaleMode === "relative") {
    const prices = samples.map((s) => s.p);
    minP = Math.min(...prices);
    const maxP = Math.max(...prices);
    range = maxP - minP;
  } else {
    minP = 0;
    range = fixedMax;
  }

  return samples.map((s, i): ChartCoord => {
    const xRatio = samples.length === 1 ? 1 : i / lastIdx;
    let yRatio: number;
    if (range <= 0) {
      // Constant-price input — collapse to the vertical center so we still
      // render a horizontal trace instead of dividing by zero.
      yRatio = 0.5;
    } else {
      const clamped = Math.max(minP, Math.min(minP + range, s.p));
      yRatio = (clamped - minP) / range;
    }
    return [padX + xRatio * innerW, padY + innerH - yRatio * innerH];
  });
}
