import { describe, expect, it } from "vitest";
import type { Market } from "@/types/market";
import { carryPriceForward, pickChartSeries } from "./eventChartSeries";

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
    outcome_prices: [],
    best_bid: null,
    best_ask: null,
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

  it("prefers outcome_label over question for the legend label", () => {
    const m = fakeMarket(1, "Will France win the 2026 World Cup?");
    m.outcome_label = "France";
    const series = pickChartSeries(
      [m],
      new Map([[1, 0.5]]),
      PALETTE,
      4,
    );
    expect(series[0]!.label).toBe("France");
  });

  it("falls back to question when outcome_label is null", () => {
    const m = fakeMarket(1, "Will GTA VI release before June 2026?");
    m.outcome_label = null;
    const series = pickChartSeries(
      [m],
      new Map([[1, 0.5]]),
      PALETTE,
      4,
    );
    expect(series[0]!.label).toBe("Will GTA VI release before June 2026?");
  });
});

describe("carryPriceForward", () => {
  const NOW = 1_800_000_000;

  it("closes a one-trade series so it has a line to draw", () => {
    // The bug this exists for: one coordinate makes smoothPath emit a bare
    // `M x y`, which paints nothing, so the outcome vanished from the chart
    // while the legend still listed it.
    expect(carryPriceForward([{ t: NOW - 3600, p: 0.14 }], NOW)).toEqual([
      { t: NOW - 3600, p: 0.14 },
      { t: NOW, p: 0.14 },
    ]);
  });

  it("carries the LAST price, not the first", () => {
    const out = carryPriceForward(
      [
        { t: NOW - 7200, p: 0.4 },
        { t: NOW - 3600, p: 0.62 },
      ],
      NOW,
    );
    expect(out[out.length - 1]).toEqual({ t: NOW, p: 0.62 });
    expect(out).toHaveLength(3);
  });

  it("leaves a market that never traded empty", () => {
    // There is no price to carry. A flat line at today's mid would draw a
    // month of history that never happened.
    expect(carryPriceForward([], NOW)).toEqual([]);
    expect(carryPriceForward([], NOW, 0.42)).toEqual([]);
  });

  it("adds nothing when the last trade is already current", () => {
    const points = [{ t: NOW, p: 0.5 }];
    expect(carryPriceForward(points, NOW)).toBe(points);
  });

  it("does not rewrite the samples it was given", () => {
    const points = [{ t: NOW - 60, p: 0.3 }];
    carryPriceForward(points, NOW);
    expect(points).toHaveLength(1);
  });

  // The bug this exists for: the headline reads the BOOK while the chart
  // reads the TAPE. A market whose book collapsed after its last print drew a
  // flat line at the stale trade price all the way to now — a Counter-Strike
  // market showed "<1% chance" beside a chart ending at 71%.
  it("closes at the live price, not the stale last trade", () => {
    const out = carryPriceForward(
      [
        { t: NOW - 7200, p: 0.47 },
        { t: NOW - 3600, p: 0.71 },
      ],
      NOW,
      0.001,
    );
    expect(out[out.length - 1]).toEqual({ t: NOW, p: 0.001 });
    expect(out).toHaveLength(3);
  });

  it("keeps the traded history intact — only the closing point is the live one", () => {
    const history = [
      { t: NOW - 7200, p: 0.47 },
      { t: NOW - 3600, p: 0.71 },
    ];
    const out = carryPriceForward(history, NOW, 0.001);
    expect(out.slice(0, 2)).toEqual(history);
  });

  it("falls back to the last trade when no live price is known", () => {
    const out = carryPriceForward([{ t: NOW - 3600, p: 0.62 }], NOW, undefined);
    expect(out[out.length - 1]).toEqual({ t: NOW, p: 0.62 });
  });

  it("ignores a non-finite live price rather than drawing a gap", () => {
    const out = carryPriceForward([{ t: NOW - 3600, p: 0.62 }], NOW, NaN);
    expect(out[out.length - 1]).toEqual({ t: NOW, p: 0.62 });
  });

  it("accepts a live price of zero — a market can genuinely be worthless", () => {
    const out = carryPriceForward([{ t: NOW - 3600, p: 0.62 }], NOW, 0);
    expect(out[out.length - 1]).toEqual({ t: NOW, p: 0 });
  });
});
