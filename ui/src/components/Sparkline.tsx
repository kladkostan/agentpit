import { useId, useMemo } from "react";
import {
  projectToViewBox,
  smoothPath,
  type SparklineSample,
} from "@/lib/chartGeometry";
import { cn } from "@/lib/utils";

interface SparklineProps {
  points: ReadonlyArray<SparklineSample>;
  width?: number;
  height?: number;
  tone?: "up" | "down" | "neutral";
  /** Extra classes for the outer <svg>. */
  className?: string;
}

const TONE_STROKE: Record<NonNullable<SparklineProps["tone"]>, string> = {
  up: "stroke-emerald-500",
  down: "stroke-rose-500",
  neutral: "stroke-muted-foreground/60",
};

const TONE_FILL: Record<NonNullable<SparklineProps["tone"]>, string> = {
  up: "text-emerald-500",
  down: "text-rose-500",
  neutral: "text-muted-foreground/40",
};

export function Sparkline({
  points,
  width = 160,
  height = 56,
  tone = "neutral",
  className,
}: SparklineProps) {
  const gradientId = useId();

  const geometry = useMemo(() => {
    if (points.length === 0) return null;
    const coords = projectToViewBox(points, {
      width,
      height,
      padX: 1,
      padY: 4,
      scaleMode: "relative",
    });
    const path = smoothPath(coords);
    const last = coords[coords.length - 1]!;
    const first = coords[0]!;
    const area =
      path + ` L ${last[0]} ${height} L ${first[0]} ${height} Z`;
    return { coords, path, area };
  }, [points, width, height]);

  if (!geometry) {
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={cn("overflow-visible text-muted-foreground/30", className)}
        aria-hidden
      >
        <line
          x1={1}
          x2={width - 1}
          y1={height / 2}
          y2={height / 2}
          stroke="currentColor"
          strokeDasharray="2 3"
          strokeWidth={1}
        />
      </svg>
    );
  }

  const last = geometry.coords[geometry.coords.length - 1]!;
  const strokeClass = TONE_STROKE[tone];
  const fillClass = TONE_FILL[tone];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      aria-hidden
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d={geometry.area}
        className={fillClass}
        fill={`url(#${gradientId})`}
      />
      <path
        d={geometry.path}
        className={strokeClass}
        fill="none"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={last[0]}
        cy={last[1]}
        r={2.5}
        className={cn(strokeClass, "fill-background")}
        strokeWidth={1.5}
      />
    </svg>
  );
}
