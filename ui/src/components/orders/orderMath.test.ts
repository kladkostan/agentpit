import { describe, expect, it } from "vitest";
import {
  aggregateLevels,
  bestAskMicro,
  bestBidMicro,
  computeMarketBuy,
  computeMarketSell,
  deriveNoAskMicro,
  dollarsFromShares,
  PRICE_TICK,
  pickSellOutcome,
  sharesFromDollars,
  SHARES_SCALE,
} from "./orderMath";
import type { OrderbookEntry } from "@/types/order";

const mkEntry = (price: number): OrderbookEntry => ({
  ORDER_ID: `${price}`,
  SIDE: "BUY",
  PRICE: price,
  REMAINING_AMOUNT: SHARES_SCALE,
  MAKER: "0x0",
  CREATED_AT: 0,
});

describe("bestAskMicro", () => {
  it("returns the lowest ask, snapped to the 0.1¢ tick like the order book", () => {
    // Raw 184_500 (18.45¢) snaps to 185_000 (18.5¢) — matching the price the
    // order book renders, so the ticket chip and the book agree to the cent.
    expect(bestAskMicro([mkEntry(184_500), mkEntry(200_000)])).toBe(185_000);
  });

  it("returns null for an empty book side", () => {
    expect(bestAskMicro([])).toBeNull();
  });
});

describe("bestBidMicro", () => {
  it("returns the highest bid, snapped to the 0.1¢ tick", () => {
    // 174_500 (17.45¢) snaps to 175_000 (17.5¢).
    expect(bestBidMicro([mkEntry(174_500), mkEntry(170_000)])).toBe(175_000);
  });

  it("returns null for an empty book side", () => {
    expect(bestBidMicro([])).toBeNull();
  });
});

describe("deriveNoAskMicro", () => {
  it("uses the NO book's own best ask when present", () => {
    expect(deriveNoAskMicro([mkEntry(825_500)], [mkEntry(174_500)])).toBe(
      826_000,
    );
  });

  it("falls back to the complement of the YES best bid when NO is empty", () => {
    // NO ask mirrors a YES bid: 1.0 − 0.175 = 0.825 → 825_000 micro.
    expect(deriveNoAskMicro([], [mkEntry(174_500), mkEntry(170_000)])).toBe(
      825_000,
    );
  });

  it("returns null when neither side is known", () => {
    expect(deriveNoAskMicro([], [])).toBeNull();
  });
});

describe("aggregateLevels", () => {
  const entry = (price: number, shares: number): OrderbookEntry => ({
    ORDER_ID: `${price}-${shares}`,
    SIDE: "BUY",
    PRICE: price,
    REMAINING_AMOUNT: shares * SHARES_SCALE,
    MAKER: "0x0",
    CREATED_AT: 0,
  });

  it("merges distinct sub-cent prices into 0.1¢ levels, summing size", () => {
    // 0.020 and 0.0201 both fall in the 0.020 level; 0.017 is its own level.
    // Before, these rendered as three "$0.02" rows.
    const levels = aggregateLevels([
      entry(20000, 100),
      entry(20100, 5),
      entry(17000, 20),
    ]);
    const byPrice = new Map(levels.map((l) => [l.price, l.size]));
    expect(levels).toHaveLength(2);
    expect(byPrice.get(20000)).toBe(105 * SHARES_SCALE);
    expect(byPrice.get(17000)).toBe(20 * SHARES_SCALE);
  });

  it("snaps each level to a multiple of the 0.1¢ tick", () => {
    const [level] = aggregateLevels([entry(20600, 10)]); // 0.0206 → 0.021
    expect(level?.price).toBe(21000);
    expect((level?.price ?? 0) % PRICE_TICK).toBe(0);
  });
});

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

const bid = (
  price: number,
  remainingShares: number,
): OrderbookEntry => ({
  ORDER_ID: `bid-${price}-${remainingShares}`,
  SIDE: "BUY",
  PRICE: Math.round(price * 1_000_000),
  REMAINING_AMOUNT: remainingShares * 1_000_000,
  MAKER: "0x0",
  CREATED_AT: 0,
});

describe("computeMarketSell", () => {
  it("returns null for an empty book", () => {
    expect(computeMarketSell([], 100)).toBeNull();
  });

  it("caps at best_bid - SLIPPAGE_CAP", () => {
    const result = computeMarketSell([bid(0.65, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.63, 5);
    expect(result!.sizeWire).toBe(50 * 1_000_000);
  });

  it("clamps price cap at MIN_PROB (0.01)", () => {
    const result = computeMarketSell([bid(0.02, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.01, 5);
  });

  it("returns null for non-positive shares", () => {
    expect(computeMarketSell([bid(0.65, 100)], 0)).toBeNull();
  });
});

describe("pickSellOutcome", () => {
  it("keeps the current outcome when the user holds it", () => {
    const holdings = new Map([["YES", 100], ["NO", 0]]);
    expect(pickSellOutcome("YES", holdings)).toBe("YES");
  });

  it("flips to the other outcome when current has zero balance", () => {
    const holdings = new Map([["YES", 0], ["NO", 50]]);
    expect(pickSellOutcome("YES", holdings)).toBe("NO");
  });

  it("returns the current outcome when nothing is held (caller surfaces error)", () => {
    const holdings = new Map([["YES", 0], ["NO", 0]]);
    expect(pickSellOutcome("YES", holdings)).toBe("YES");
  });

  it("returns the current outcome when no holdings map is supplied yet", () => {
    expect(pickSellOutcome("YES", new Map())).toBe("YES");
  });

  it("never picks an outcome with a non-positive balance", () => {
    const holdings = new Map([["YES", 0], ["NO", -5]]);
    expect(pickSellOutcome("YES", holdings)).toBe("YES");
  });
});
