import { describe, expect, it } from "vitest";
import type { Market } from "@/types/market";
import { sortMarketsByYesMid } from "./eventOutcomes";

function m(id: number, label = `m${id}`): Market {
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
