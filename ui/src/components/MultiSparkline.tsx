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
const PAD_X = 4;
const PAD_Y = 6;

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
          padX: PAD_X,
          padY: PAD_Y,
        }),
      })),
    [series, width, height],
  );

  // Gridlines align with the padded data area, not the raw viewBox edges,
  // so the 50% line sits exactly between the projected 0 and 1 prices.
  const innerH = height - PAD_Y * 2;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("block h-[180px] w-full overflow-visible", className)}
      aria-hidden
    >
      {/* Gridlines */}
      {GRIDLINE_Y_PCT.map((pct) => {
        const y = PAD_Y + innerH - (pct / 100) * innerH;
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
