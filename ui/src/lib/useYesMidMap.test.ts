import { describe, expect, it } from "vitest";
import type { OrderbookEntry, OrderbookResponse } from "@/types/order";
import { computeMid, deriveNoCents } from "./useYesMid";

function entry(price: number): OrderbookEntry {
  return {
    ORDER_ID: "x",
    SIDE: "BUY",
    PRICE: price,
    REMAINING_AMOUNT: 1,
    MAKER: "m",
    CREATED_AT: 0,
  };
}

function book(bids: number[], asks: number[]): OrderbookResponse {
  return {
    market_id: 1,
    outcome: "Yes",
    bids: bids.map(entry),
    asks: asks.map(entry),
  };
}

describe("computeMid", () => {
  it("returns midpoint when both sides exist", () => {
    // best bid 0.4, best ask 0.46 → mid 0.43
    expect(computeMid(book([400_000, 380_000], [460_000, 480_000]))).toBeCloseTo(
      0.43,
      5,
    );
  });

  it("falls back to the only available side", () => {
    expect(computeMid(book([], [200_000]))).toBeCloseTo(0.2, 5);
    expect(computeMid(book([800_000], []))).toBeCloseTo(0.8, 5);
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
