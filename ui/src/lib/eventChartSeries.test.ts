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
