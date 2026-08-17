import { describe, expect, it } from "vitest";
import type { Market } from "@/types/market";
import {
  buyChipCents,
  pickInitialSelection,
  sortMarketsByYesMid,
  yesPriceMap,
} from "./eventOutcomes";

function m(id: number, label = `m${id}`, yesPrice: number | null = null): Market {
  return {
    market_id: id,
    question: `q${id}`,
    slug: `s${id}`,
    description: "",
    erc1155_tokens: [[`t-${id}-y`, "Yes"], [`t-${id}-n`, "No"]],
    start_date: 0,
    end_date: null,
    market_state: "ACTIVE",
    resolved_outcome: null,
    polymarket_id: null,
    condition_id: `0x${id}`,
    event_id: null,
    outcome_label: label,
    icon_url: null,
    outcome_prices: yesPrice === null ? [] : [yesPrice, 1 - yesPrice],
    best_bid: null,
    best_ask: null,
  };
}

describe("sortMarketsByYesMid", () => {
  it("orders markets by descending YES mid", () => {
    const markets = [m(1), m(2), m(3)];
    const mids = new Map([
      [1, 0.18],
      [2, 0.42],
      [3, 0.09],
    ]);
    expect(sortMarketsByYesMid(markets, mids).map((x) => x.market_id)).toEqual([
      2, 1, 3,
    ]);
  });

  it("places markets without a mid at the bottom in original order", () => {
    const markets = [m(1), m(2), m(3), m(4)];
    const mids = new Map([
      [2, 0.5],
      [4, 0.1],
    ]);
    expect(sortMarketsByYesMid(markets, mids).map((x) => x.market_id)).toEqual([
      2, 4, 1, 3,
    ]);
  });

  it("does not mutate the input array", () => {
    const markets = [m(1), m(2)];
    const snapshot = markets.slice();
    sortMarketsByYesMid(markets, new Map([[1, 0.1], [2, 0.5]]));
    expect(markets).toEqual(snapshot);
  });

  it("returns a stable order when mids are equal", () => {
    const markets = [m(1), m(2), m(3)];
    const mids = new Map([
      [1, 0.5],
      [2, 0.5],
      [3, 0.5],
    ]);
    expect(sortMarketsByYesMid(markets, mids).map((x) => x.market_id)).toEqual([
      1, 2, 3,
    ]);
  });
});

describe("yesPriceMap", () => {
  it("keys the YES price by market id", () => {
    const map = yesPriceMap([m(1, "a", 0.62), m(2, "b", 0.11)]);
    expect(map.get(1)).toBeCloseTo(0.62, 5);
    expect(map.get(2)).toBeCloseTo(0.11, 5);
  });

  it("omits markets with no usable price so they sort last", () => {
    const map = yesPriceMap([m(1, "a", 0.62), m(2, "b", null)]);
    expect(map.has(2)).toBe(false);
    expect(map.size).toBe(1);
  });
});

describe("buyChipCents", () => {
  it("prices YES at its own ask and NO through the YES bid", () => {
    const { yes, no } = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: 0.6,
      best_ask: 0.64,
    });
    expect(yes).toBeCloseTo(64, 5);
    expect(no).toBeCloseTo(40, 5);
  });

  it("returns null per side when that side has no resting order", () => {
    const { yes, no } = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: null,
      best_ask: null,
    });
    expect(yes).toBeNull();
    expect(no).toBeNull();
  });

  it("computes each side independently in the mixed shape (one side quoted, one not)", () => {
    // 19 of 203 production markets have exactly one side resting.
    const bidOnly = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: 0.6,
      best_ask: null,
    });
    expect(bidOnly.yes).toBeNull();
    expect(bidOnly.no).toBeCloseTo(40, 5);

    const askOnly = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: null,
      best_ask: 0.64,
    });
    expect(askOnly.yes).toBeCloseTo(64, 5);
    expect(askOnly.no).toBeNull();
  });
});

describe("pickInitialSelection", () => {
  // Ranked by probability: the reader clicked m3 but m1 sits on top.
  const ordered = [m(1), m(2), m(3)];

  it("opens the requested market rather than the top-ranked one", () => {
    // The complaint: linking a "25 bps increase" position opened "no change",
    // because the leaderboard is sorted by likelihood.
    expect(pickInitialSelection(ordered, null, "s3", null)).toEqual({
      marketId: 3,
      outcome: "Yes",
    });
  });

  it("falls back to the top-ranked market with no request", () => {
    expect(pickInitialSelection(ordered, null, null, null)).toEqual({
      marketId: 1,
      outcome: "Yes",
    });
  });

  it("falls back to the top-ranked market when the slug is unknown", () => {
    // A stale link must still open something.
    expect(pickInitialSelection(ordered, null, "gone", null)).toEqual({
      marketId: 1,
      outcome: "Yes",
    });
  });

  it("prefers the live window of a rotating series when nothing was asked", () => {
    expect(pickInitialSelection(ordered, m(9), null, null)?.marketId).toBe(9);
  });

  it("lets an explicit request beat the live window", () => {
    expect(pickInitialSelection(ordered, m(9), "s2", null)?.marketId).toBe(2);
  });

  it("honours the requested outcome when the market carries it", () => {
    expect(pickInitialSelection(ordered, null, "s3", "No")).toEqual({
      marketId: 3,
      outcome: "No",
    });
  });

  it("ignores an outcome the requested market does not have", () => {
    expect(pickInitialSelection(ordered, null, "s3", "Maybe")?.outcome).toBe("Yes");
  });

  it("does not carry a requested outcome onto a fallback market", () => {
    // The reader never chose a side on this row, so asserting one would lie.
    expect(pickInitialSelection(ordered, null, "gone", "No")).toEqual({
      marketId: 1,
      outcome: "Yes",
    });
  });

  it("returns null when the event has no markets", () => {
    expect(pickInitialSelection([], null, null, null)).toBeNull();
  });
});
