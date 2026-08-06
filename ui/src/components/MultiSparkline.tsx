import { useEffect, useId, useMemo, useRef, useState } from "react";
import { projectToViewBox, smoothPath } from "@/lib/chartGeometry";
import type { SparklineSample } from "@/lib/chartGeometry";
import { cn } from "@/lib/utils";

export interface MultiSparklineSeries {
  id: string | number;
  color: string;
  label?: string;
  points: ReadonlyArray<SparklineSample>;
}

export interface MultiSparklineHoverPoint {
  id: string | number;
  color: string;
  label: string;
  sample: SparklineSample;
  coord: readonly [x: number, y: number];
}

export interface MultiSparklineHoverState {
  x: number;
  points: ReadonlyArray<MultiSparklineHoverPoint>;
}

interface TooltipRowLayout {
  id: string | number;
  color: string;
  labelText: string;
  pctText: string;
  x: number;
  y: number;
  w: number;
  h: number;
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
  onHoverChange?: (next: MultiSparklineHoverState | null) => void;
  className?: string;
}

/** Interior gridline positions, in % of the chart's height. */
export const GRIDLINE_Y_PCT = [25, 50, 75] as const;
/** Default interior gridlines as domain fractions (0–1). */
const DEFAULT_GRID_RATIOS = GRIDLINE_Y_PCT.map((p) => p / 100);
/** Inner-padding around the projected data area, in viewBox units. */
export const PAD_X = 4;
export const PAD_Y = 6;
const HOVER_DOT_RADIUS = 4.8;

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function formatHoverPct(fraction: number): string {
  const pct = Math.round(fraction * 1000) / 10;
  return `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`;
}

const TOOLTIP_FONT_SIZE = 11;
const TOOLTIP_LABEL_FONT_WEIGHT = 400;
const TOOLTIP_PCT_FONT_WEIGHT = 700;
const TOOLTIP_FONT_FAMILY =
  '"Instrument Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';

const textMeasureContext = (() => {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  return canvas.getContext("2d");
})();

function measureTooltipTextWidth(labelText: string, pctText: string): number {
  if (textMeasureContext) {
    textMeasureContext.font = `${TOOLTIP_LABEL_FONT_WEIGHT} ${TOOLTIP_FONT_SIZE}px ${TOOLTIP_FONT_FAMILY}`;
    const labelW = textMeasureContext.measureText(labelText).width;
    textMeasureContext.font = `${TOOLTIP_PCT_FONT_WEIGHT} ${TOOLTIP_FONT_SIZE}px ${TOOLTIP_FONT_FAMILY}`;
    const pctW = textMeasureContext.measureText(pctText).width;
    return Math.ceil(labelW + pctW);
  }
  // Fallback width estimate for non-browser environments.
  return Math.ceil((labelText.length + pctText.length) * 6.9);
}

function nearestCoordIndex(
  coords: ReadonlyArray<readonly [number, number]>,
  x: number,
): number {
  let bestIdx = 0;
  let bestDist = Number.POSITIVE_INFINITY;
  for (let i = 0; i < coords.length; i++) {
    const d = Math.abs(coords[i]![0] - x);
    if (d < bestDist) {
      bestDist = d;
      bestIdx = i;
    }
  }
  return bestIdx;
}

function interpolateAtX(
  coords: ReadonlyArray<readonly [number, number]>,
  points: ReadonlyArray<SparklineSample>,
  x: number,
): { sample: SparklineSample; coord: readonly [number, number] } | null {
  if (coords.length === 0 || points.length === 0) return null;

  if (coords.length === 1 || points.length === 1) {
    return {
      sample: points[0]!,
      coord: [x, coords[0]![1]],
    };
  }

  const idx = nearestCoordIndex(coords, x);
  const x0 = coords[idx]![0];

  if (x <= x0 && idx === 0) {
    return {
      sample: points[0]!,
      coord: [x, coords[0]![1]],
    };
  }

  if (x >= x0 && idx === coords.length - 1) {
    const last = coords.length - 1;
    return {
      sample: points[last]!,
      coord: [x, coords[last]![1]],
    };
  }

  const right = x >= x0 ? idx + 1 : idx;
  const left = right - 1;
  const c0 = coords[left]!;
  const c1 = coords[right]!;
  const p0 = points[left]!;
  const p1 = points[right]!;

  const dx = c1[0] - c0[0];
  const ratio = dx <= 0 ? 0 : clamp((x - c0[0]) / dx, 0, 1);
  const y = c0[1] + (c1[1] - c0[1]) * ratio;

  return {
    sample: {
      t: p0.t + (p1.t - p0.t) * ratio,
      p: p0.p + (p1.p - p0.p) * ratio,
    },
    coord: [x, y],
  };
}

export function MultiSparkline({
  series,
  width = 600,
  height = 180,
  maxP = 1,
  gridRatios = DEFAULT_GRID_RATIOS,
  onHoverChange,
  className,
}: MultiSparklineProps) {
  const [hoverX, setHoverX] = useState<number | null>(null);
  const clipId = useId().replace(/:/g, "-");
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [renderScale, setRenderScale] = useState({ sx: 1, sy: 1 });

  useEffect(() => {
    const node = svgRef.current;
    if (!node) return;

    const updateScale = () => {
      const rect = node.getBoundingClientRect();
      const sx = rect.width > 0 ? rect.width / width : 1;
      const sy = rect.height > 0 ? rect.height / height : 1;
      setRenderScale({ sx, sy });
    };

    updateScale();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateScale);
    observer.observe(node);
    return () => observer.disconnect();
  }, [width, height]);

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

  const hover = useMemo<MultiSparklineHoverState | null>(() => {
    if (hoverX === null) return null;
    const points: MultiSparklineHoverPoint[] = [];
    for (const s of projected) {
      if (s.coords.length === 0) continue;
      const interpolated = interpolateAtX(s.coords, s.points, hoverX);
      if (!interpolated) continue;
      points.push({
        id: s.id,
        color: s.color,
        label: s.label ?? String(s.id),
        sample: interpolated.sample,
        coord: interpolated.coord,
      });
    }
    if (points.length === 0) return null;
    return { x: hoverX, points };
  }, [hoverX, projected]);

  useEffect(() => {
    onHoverChange?.(hover);
  }, [hover, onHoverChange]);

  // Gridlines align with the padded data area, not the raw viewBox edges,
  // so the 50% line sits exactly between the projected 0 and 1 prices.
  const innerH = height - PAD_Y * 2;

  const tooltip = useMemo(() => {
    if (!hover) return null;
    const rowH = 26;
    const rowGap = 6;
    const paddingX = 10;
    const dotW = 6;
    const dotGap = 8;
    const xGap = 12;

    const preferredRightX = hover.x + xGap;

    const baseRows = hover.points
      .map((p): TooltipRowLayout & { targetY: number } => {
        const pctText = formatHoverPct(p.sample.p);
        const labelText = `${p.label} `;
        const textW = measureTooltipTextWidth(labelText, pctText);
        const w = Math.ceil(paddingX * 2 + dotW + dotGap + textW);
        const rightFits = preferredRightX + w <= width - PAD_X;
        const leftX = hover.x - xGap - w;
        const x = rightFits ? preferredRightX : Math.max(PAD_X, leftX);
        return {
          id: p.id,
          color: p.color,
          labelText,
          pctText,
          x,
          y: 0,
          w,
          h: rowH,
          targetY: p.coord[1] - rowH / 2,
        };
      })
      .sort((a, b) => a.targetY - b.targetY);

    const minY = PAD_Y;
    const maxY = height - PAD_Y - rowH;
    for (let i = 0; i < baseRows.length; i++) {
      const prevBottom = i === 0 ? minY : baseRows[i - 1]!.y + rowH + rowGap;
      baseRows[i]!.y = Math.max(baseRows[i]!.targetY, prevBottom);
    }

    const overflow = baseRows.length > 0 ? baseRows[baseRows.length - 1]!.y - maxY : 0;
    if (overflow > 0) {
      for (const row of baseRows) {
        row.y = Math.max(minY, row.y - overflow);
      }
    }

    return {
      paddingX,
      dotW,
      dotGap,
      rows: baseRows,
    };
  }, [height, hover, width]);

  const handlePointerMove = (clientX: number, left: number, pixelWidth: number) => {
    const ratio = pixelWidth > 0 ? (clientX - left) / pixelWidth : 0;
    setHoverX(clamp(ratio * width, PAD_X, width - PAD_X));
  };

  const circleXRadiusScale =
    renderScale.sx > 0 && renderScale.sy > 0 ? renderScale.sy / renderScale.sx : 1;

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ height }}
      className={cn("block w-full overflow-visible", className)}
      onPointerMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        handlePointerMove(e.clientX, rect.left, rect.width);
      }}
      onPointerLeave={() => setHoverX(null)}
      aria-hidden
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={hover?.x ?? width} height={height} />
        </clipPath>
      </defs>

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
            className="text-foreground/[0.04]"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Series paths; on hover, dim full path and highlight only the history up to cursor. */}
      {projected.map((s) => {
        if (s.coords.length === 0) return null;
        const d = smoothPath(s.coords);
        return (
          <g key={s.id}>
            <path
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={1.5}
              strokeOpacity={hover ? 0.2 : 1}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            {hover ? (
              <path
                d={d}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
                clipPath={`url(#${clipId})`}
              />
            ) : null}
          </g>
        );
      })}

      {!hover
        ? projected.map((s) => {
          if (s.coords.length === 0) return null;
          const last = s.coords[s.coords.length - 1]!;
          return (
            <ellipse
              key={`${s.id}-last-dot`}
              cx={last[0]}
              cy={last[1]}
              rx={2.5 * circleXRadiusScale}
              ry={2.5}
              fill={s.color}
              stroke="hsl(var(--background))"
              strokeWidth={1.25}
              vectorEffect="non-scaling-stroke"
            />
          );
        })
        : null}

      {hover ? (
        <line
          x1={hover.x}
          x2={hover.x}
          y1={PAD_Y}
          y2={height - PAD_Y}
          stroke="currentColor"
          strokeWidth={1}
          className="text-foreground/20"
          vectorEffect="non-scaling-stroke"
        />
      ) : null}

      {hover
        ? hover.points.map((p) => (
          <ellipse
            key={`${p.id}-hover-dot`}
            cx={p.coord[0]}
            cy={p.coord[1]}
            rx={HOVER_DOT_RADIUS * circleXRadiusScale}
            ry={HOVER_DOT_RADIUS}
            fill={p.color}
            stroke="hsl(var(--background))"
            strokeWidth={2.2}
            vectorEffect="non-scaling-stroke"
          />
        ))
        : null}

      {hover && tooltip ? (
        <g>
          {tooltip.rows.map((row) => {
            const y = row.y + row.h / 2;
            return (
              <g key={`${row.id}-tooltip`}>
                <rect
                  x={row.x}
                  y={row.y}
                  width={row.w}
                  height={row.h}
                  rx={7}
                  fill="hsl(var(--card))"
                  fillOpacity={0.96}
                  stroke="hsl(var(--border))"
                  strokeOpacity={0.75}
                />
                <ellipse
                  cx={row.x + tooltip.paddingX + tooltip.dotW / 2}
                  cy={y}
                  rx={(tooltip.dotW / 2) * circleXRadiusScale}
                  ry={tooltip.dotW / 2}
                  fill={row.color}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={row.x + tooltip.paddingX + tooltip.dotW + tooltip.dotGap}
                  y={y + 0.5}
                  fill="hsl(var(--foreground))"
                  fontSize={TOOLTIP_FONT_SIZE}
                  fontWeight={TOOLTIP_LABEL_FONT_WEIGHT}
                  fontFamily={TOOLTIP_FONT_FAMILY}
                  dominantBaseline="middle"
                >
                  <tspan>{row.labelText}</tspan>
                  <tspan fontWeight={TOOLTIP_PCT_FONT_WEIGHT}>{row.pctText}</tspan>
                </text>
              </g>
            );
          })}
        </g>
      ) : null}
    </svg>
  );
}
