import { describe, expect, it } from "vitest";
import { computeMarketBuy, dollarsFromShares, sharesFromDollars } from "./orderMath";
import type { OrderbookEntry } from "@/types/order";

describe("sharesFromDollars", () => {
  it("converts $50 at 0.65 to 76.923 shares (rounded down)", () => {
    expect(sharesFromDollars(50, 0.65)).toBeCloseTo(76.923076, 5);
  });

  it("returns 0 when price is 0", () => {
    expect(sharesFromDollars(50, 0)).toBe(0);
  });

  it("returns 0 when amount is 0", () => {
    expect(sharesFromDollars(0, 0.65)).toBe(0);
  });
});

describe("dollarsFromShares", () => {
  it("converts 100 shares at 0.65 to $65", () => {
    expect(dollarsFromShares(100, 0.65)).toBeCloseTo(65, 5);
  });

  it("returns 0 when shares is 0", () => {
    expect(dollarsFromShares(0, 0.65)).toBe(0);
  });

  it("round-trips: dollarsFromShares(sharesFromDollars(amt, p), p) ≈ amt", () => {
    expect(dollarsFromShares(sharesFromDollars(50, 0.65), 0.65)).toBeCloseTo(50, 4);
  });
});

const ask = (
  price: number,
  remainingShares: number,
): OrderbookEntry => ({
  ORDER_ID: `ask-${price}-${remainingShares}`,
  SIDE: "SELL",
  PRICE: Math.round(price * 1_000_000),
  REMAINING_AMOUNT: remainingShares * 1_000_000,
  MAKER: "0x0",
  CREATED_AT: 0,
});

describe("computeMarketBuy", () => {
  it("returns null for an empty book", () => {
    expect(computeMarketBuy([], 50)).toBeNull();
  });

  it("caps at best_ask + SLIPPAGE_CAP", () => {
    const result = computeMarketBuy([ask(0.65, 100)], 50);
    expect(result).not.toBeNull();
    expect(result!.priceCap).toBeCloseTo(0.67, 5);
    expect(result!.sizeWire).toBe(Math.floor((50 * 1_000_000) / 0.67));
  });

  it("clamps price cap at MAX_PROB (0.99)", () => {
    const result = computeMarketBuy([ask(0.98, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.99, 5);
  });

  it("returns null for non-positive amount", () => {
    expect(computeMarketBuy([ask(0.65, 100)], 0)).toBeNull();
    expect(computeMarketBuy([ask(0.65, 100)], -1)).toBeNull();
  });
});
