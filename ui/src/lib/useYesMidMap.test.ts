import { describe, expect, it } from "vitest";
import type { OrderbookEntry, OrderbookResponse } from "@/types/order";
import { computeMid } from "./useYesMid";

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
