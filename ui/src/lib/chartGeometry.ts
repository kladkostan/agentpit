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
}

/** Project sparkline samples into chart-local SVG coords.
 *
 *  X-axis is by sample index, not by timestamp — sparse trade streams stay
 *  comfortably spaced rather than clumping near recent activity.
 */
export function projectToViewBox(
  samples: ReadonlyArray<SparklineSample>,
  { width, height, padX = 0, padY = 0, scaleMode = "fixed" }: ProjectionDims,
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
    range = 1_000_000;
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
