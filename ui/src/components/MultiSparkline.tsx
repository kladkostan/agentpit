import { useMemo, useState } from "react";
import { projectToViewBox, smoothPath } from "@/lib/chartGeometry";
import type { SparklineSample, ChartCoord } from "@/lib/chartGeometry";
import { cn } from "@/lib/utils";

export interface MultiSparklineSeries {
  id: string | number;
  color: string;
  label?: string;
  points: ReadonlyArray<SparklineSample>;
}

interface MultiSparklineProps {
  series: ReadonlyArray<MultiSparklineSeries>;
  /** Logical viewBox width — actual rendered width is controlled by CSS. */
  width?: number;
  height?: number;
  /** Upper bound of the vertical domain as a probability fraction [0, 1].
   *  Defaults to a full 0–100% axis; pass a focused value to zoom onto
   *  low-probability data. */
  maxP?: number;
  /** Interior gridline positions as fractions of the domain (0–1). Defaults
   *  to the quartile lines. The 0 and top edges are intentionally omitted. */
  gridRatios?: ReadonlyArray<number>;
  className?: string;
}

/** Interior gridline positions, in % of the chart's height. */
export const GRIDLINE_Y_PCT = [25, 50, 75] as const;
/** Default interior gridlines as domain fractions (0–1). */
const DEFAULT_GRID_RATIOS = GRIDLINE_Y_PCT.map((p) => p / 100);
/** Inner-padding around the projected data area, in viewBox units. */
export const PAD_X = 4;
export const PAD_Y = 6;
/** Extra right margin (viewBox units) reserved for floating end-labels. */
const LABEL_MARGIN = 120;

/** Linearly interpolate the Y coordinate of a series at a given viewBox X. */
function interpolateY(
  coords: ReadonlyArray<ChartCoord>,
  vbX: number,
): [number, number] | null {
  for (let i = 0; i < coords.length - 1; i++) {
    const [x1, y1] = coords[i]!;
    const [x2, y2] = coords[i + 1]!;
    if (x1 <= vbX && vbX <= x2) {
      const t = x2 === x1 ? 0 : (vbX - x1) / (x2 - x1);
      return [vbX, y1 + t * (y2 - y1)];
    }
  }
  return null;
}

/** Convert a projected Y coordinate back to a probability fraction [0, maxP]. */
function pFromY(y: number, innerH: number, maxP: number): number {
  return Math.max(0, Math.min(maxP, ((PAD_Y + innerH - y) / innerH) * maxP));
}

/** Format a probability fraction as a percentage label, e.g. 0.527 → "53%" */
function fmtPct(p: number): string {
  return `${Math.round(p * 100)}%`;
}

export function MultiSparkline({
  series,
  width = 600,
  height = 180,
  maxP = 1,
  gridRatios = DEFAULT_GRID_RATIOS,
  className,
}: MultiSparklineProps) {
  const [hoverX, setHoverX] = useState<number | null>(null);

  const projected = useMemo(
    () =>
      series.map((s) => ({
        ...s,
        coords: projectToViewBox(s.points, {
          width,
          height,
          padX: PAD_X,
          padY: PAD_Y,
          fixedMax: maxP,
        }),
      })),
    [series, width, height, maxP],
  );

  // Gridlines align with the padded data area, not the raw viewBox edges,
  // so the 50% line sits exactly between the projected 0 and 1 prices.
  const innerH = height - PAD_Y * 2;

  // Interpolated hover points: [x, y] for each series, or null.
  const hoverPoints = useMemo(() => {
    if (hoverX === null) return null;
    return projected.map((s) =>
      s.coords.length < 2 ? null : interpolateY(s.coords, hoverX),
    );
  }, [hoverX, projected]);

  // Total viewBox width expanded to fit right-side floating labels.
  const totalWidth = width + LABEL_MARGIN;

  return (
    <svg
      viewBox={`0 0 ${totalWidth} ${height}`}
      preserveAspectRatio="none"
      style={{ height }}
      className={cn("block w-full cursor-crosshair overflow-visible", className)}
      aria-hidden
      onMouseMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        // Map from CSS pixel coords to viewBox coords (only the data region).
        const dataW = (rect.width * width) / totalWidth;
        const relX = ((e.clientX - rect.left) / dataW) * width;
        const clamped = Math.max(PAD_X, Math.min(width - PAD_X, relX));
        setHoverX(clamped);
      }}
      onMouseLeave={() => setHoverX(null)}
    >
      {/* Gridlines */}
      {gridRatios.map((ratio) => {
        const y = PAD_Y + innerH - ratio * innerH;
        return (
          <line
            key={ratio}
            x1={0}
            x2={width}
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeWidth={1}
            className="text-foreground/[0.06]"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Series paths */}
      {projected.map((s) => {
        if (s.coords.length === 0) return null;
        const d = smoothPath(s.coords);
        return (
          <path
            key={s.id}
            d={d}
            fill="none"
            stroke={s.color}
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Hover crosshair + intersection dots */}
      {hoverX !== null && hoverPoints !== null && (
        <g>
          {/* Vertical crosshair */}
          <line
            x1={hoverX}
            x2={hoverX}
            y1={PAD_Y}
            y2={height - PAD_Y}
            stroke="currentColor"
            strokeWidth={1}
            className="text-foreground/25"
            vectorEffect="non-scaling-stroke"
          />
          {/* Intersection dots */}
          {hoverPoints.map((pt, i) => {
            if (!pt) return null;
            const s = projected[i]!;
            return (
              <circle
                key={s.id}
                cx={pt[0]}
                cy={pt[1]}
                r={3.5}
                fill={s.color}
                stroke="hsl(var(--background))"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </g>
      )}

      {/* Floating labels — end-of-line when idle, hover value when active */}
      {projected.map((s, i) => {
        if (s.coords.length === 0) return null;

        let anchorPt: readonly [number, number];
        let prob: number;

        if (hoverX !== null && hoverPoints !== null && hoverPoints[i]) {
          anchorPt = hoverPoints[i]!;
          prob = pFromY(anchorPt[1], innerH, maxP);
        } else {
          // Default: label at the last data point
          anchorPt = s.coords[s.coords.length - 1]!;
          // Reverse-project the last point's Y to get its probability
          prob = pFromY(anchorPt[1], innerH, maxP);
        }

        const [, y] = anchorPt;
        const labelX = width + 10;
        // Clamp vertically so labels don't overflow the chart
        const labelY = Math.max(PAD_Y + 14, Math.min(height - PAD_Y - 6, y));

        const name = s.label ?? "";
        const pctStr = fmtPct(prob);

        return (
          <g key={s.id}>
            {/* Connector tick from the line end to the label */}
            <line
              x1={anchorPt[0]}
              x2={labelX - 4}
              y1={y}
              y2={labelY}
              stroke={s.color}
              strokeWidth={1}
              strokeDasharray="2 3"
              opacity={0.5}
              vectorEffect="non-scaling-stroke"
            />
            {/* Percentage badge */}
            <text
              x={labelX}
              y={labelY + 5}
              fill={s.color}
              fontSize={15}
              fontWeight={700}
              fontFamily="monospace"
              dominantBaseline="middle"
            >
              {pctStr}
            </text>
          </g>
        );
      })}

      {/* End-of-line solid dot (hidden while hovering) */}
      {hoverX === null &&
        projected.map((s) => {
          if (s.coords.length === 0) return null;
          const last = s.coords[s.coords.length - 1]!;
          return (
            <circle
              key={s.id}
              cx={last[0]}
              cy={last[1]}
              r={2.5}
              fill={s.color}
              stroke="hsl(var(--background))"
              strokeWidth={1.25}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
    </svg>
  );
}
