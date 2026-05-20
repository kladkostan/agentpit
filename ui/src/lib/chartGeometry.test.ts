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
    expect(path.match(/C/g)?.length).toBe(2);
  });
});

import { niceChartScale, projectToViewBox } from "./chartGeometry";

describe("niceChartScale", () => {
  it("rounds a 0–0.227 data range up to a focused 0–0.25 window", () => {
    // The 2026 World Cup favorites top out around 22.7% — the axis should
    // zoom from the default 0–100% down to a tight 0–25%.
    const { max, ticks } = niceChartScale(0.227);
    expect(max).toBeCloseTo(0.25, 6);
    expect(ticks.map((t) => Math.round(t * 100))).toEqual([0, 5, 10, 15, 20, 25]);
  });

  it("keeps the floor at 0 and the max as the top tick", () => {
    const { max, ticks } = niceChartScale(0.08);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBeCloseTo(max, 6);
  });

  it("scales a mid-range dataset to clean round bounds", () => {
    const { max, ticks } = niceChartScale(0.6);
    expect(max).toBeCloseTo(0.6, 6);
    expect(ticks.map((t) => Math.round(t * 100))).toEqual([0, 20, 40, 60]);
  });

  it("never exceeds a full 0–100% window", () => {
    const { max, ticks } = niceChartScale(0.97);
    expect(max).toBeCloseTo(1, 6);
    expect(ticks[ticks.length - 1]).toBeCloseTo(1, 6);
  });

  it("falls back to a full 0–100% window for degenerate input", () => {
    for (const bad of [0, -0.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      const { max, ticks } = niceChartScale(bad);
      expect(max).toBe(1);
      expect(ticks).toEqual([0, 0.25, 0.5, 0.75, 1]);
    }
  });
});

describe("projectToViewBox", () => {
  const dims = { width: 100, height: 50, padX: 0, padY: 0 };

  it("uses an explicit fixedMax to focus the vertical domain", () => {
    // With the domain capped at 250_000 (25%), a 250_000 price sits at the
    // top and 125_000 at the vertical center.
    const out = projectToViewBox(
      [
        { t: 0, p: 0 },
        { t: 1, p: 125_000 },
        { t: 2, p: 250_000 },
      ],
      { ...dims, fixedMax: 250_000 },
    );
    expect(out.map(([, y]) => y)).toEqual([50, 25, 0]);
  });

  it("clamps prices above fixedMax to the top edge", () => {
    const out = projectToViewBox(
      [{ t: 0, p: 900_000 }],
      { ...dims, fixedMax: 250_000 },
    );
    expect(out[0]![1]).toBe(0);
  });

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

  it("relative scaleMode stretches the input price range across the full height", () => {
    // A market trading between 0.45 and 0.55 looks near-flat under the
    // default fixed scale; relative mode auto-scales it so the curve fills
    // the chart — same behavior the home-page Sparkline had pre-extraction.
    const out = projectToViewBox(
      [
        { t: 0, p: 450_000 },
        { t: 1, p: 500_000 },
        { t: 2, p: 550_000 },
      ],
      { ...dims, scaleMode: "relative" },
    );
    expect(out.map(([, y]) => y)).toEqual([50, 25, 0]);
  });

  it("relative scaleMode collapses constant-price series to the vertical center", () => {
    // Avoid divide-by-zero when min == max; the row collapses to the
    // midline so we still see a horizontal trace.
    const out = projectToViewBox(
      [
        { t: 0, p: 500_000 },
        { t: 1, p: 500_000 },
      ],
      { ...dims, scaleMode: "relative" },
    );
    expect(out.map(([, y]) => y)).toEqual([25, 25]);
  });
});
