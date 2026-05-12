import { describe, expect, it } from "vitest";
import { dollarsFromShares, sharesFromDollars } from "./orderMath";

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
