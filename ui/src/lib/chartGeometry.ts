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
