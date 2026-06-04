import { describe, expect, it } from "vitest";
import type { OrderBookLevel, OrderBookSummary } from "@/types/order";
import { computeMid, deriveNoCents } from "./useYesMid";

function lvl(price: number): OrderBookLevel {
  return { price: String(price), size: "1" };
}

function book(bids: number[], asks: number[]): OrderBookSummary {
  return {
    market: "0xc",
    asset_id: "1",
    timestamp: "0",
    hash: "",
    bids: bids.map(lvl),
    asks: asks.map(lvl),
    min_order_size: "0",
    tick_size: "0.001",
    neg_risk: false,
    last_trade_price: "0",
  };
}

describe("computeMid", () => {
  it("returns midpoint when both sides exist", () => {
    // best bid 0.4, best ask 0.46 → mid 0.43
    expect(computeMid(book([0.4, 0.38], [0.46, 0.48]))).toBeCloseTo(0.43, 5);
  });

  it("falls back to the only available side", () => {
    expect(computeMid(book([], [0.2]))).toBeCloseTo(0.2, 5);
    expect(computeMid(book([0.8], []))).toBeCloseTo(0.8, 5);
  });

  it("returns null when the book is empty or missing", () => {
    expect(computeMid(book([], []))).toBeNull();
    expect(computeMid(undefined)).toBeNull();
  });
});

describe("deriveNoCents", () => {
  it("uses the NO book's own mid when it exists", () => {
    // YES 0.30, NO 0.68 — books disagree by 2¢; surface NO's own mid so
    // the arb is visible rather than masking it as 70¢.
    expect(deriveNoCents(0.3, 0.68)).toBeCloseTo(68, 5);
  });

  it("falls back to 100 − YES when the NO book is empty", () => {
    expect(deriveNoCents(0.3, null)).toBeCloseTo(70, 5);
  });

  it("returns null when neither side has a mid", () => {
    expect(deriveNoCents(null, null)).toBeNull();
  });

  it("uses NO mid even when YES mid is unknown", () => {
    expect(deriveNoCents(null, 0.62)).toBeCloseTo(62, 5);
  });
});
