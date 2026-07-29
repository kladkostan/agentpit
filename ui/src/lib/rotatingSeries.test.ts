import { describe, expect, it } from "vitest";
import { detectRotatingSeries } from "./rotatingSeries";
import type { Market, MarketState } from "@/types/market";

const BASE = 1_781_200_000;

/** A window market closing at `endSec`. `start_date` is deliberately ~24h
 *  before (mirroring upstream's listing time) to prove detection ignores it. */
function win(id: number, endSec: number, state: MarketState = "ACTIVE"): Market {
  return {
    market_id: id,
    question: `window ${id}`,
    slug: `w-${id}`,
    description: "",
    erc1155_tokens: [
      [`${id}-up`, "Up"],
      [`${id}-down`, "Down"],
    ],
    start_date: endSec - 86_400,
    end_date: endSec,
    market_state: state,
    resolved_outcome: null,
    polymarket_id: null,
    condition_id: `0x${id}`,
    event_id: 1,
    outcome_label: null,
    icon_url: null,
    outcome_prices: [],
    best_bid: null,
    best_ask: null,
  };
}

describe("detectRotatingSeries", () => {
  it("returns null for fewer than two markets", () => {
    expect(detectRotatingSeries([win(1, BASE)], BASE - 10)).toBeNull();
    expect(detectRotatingSeries([], BASE)).toBeNull();
  });

  it("returns null for a shared-window event (all markets close together)", () => {
    // e.g. World Cup winner — 3 outcomes all resolving at the tournament end.
    const ms = [win(1, BASE), win(2, BASE), win(3, BASE)];
    expect(detectRotatingSeries(ms, BASE - 10)).toBeNull();
  });

  it("returns null when closes are spaced beyond the cadence ceiling", () => {
    const day = 86_400;
    const ms = [win(1, BASE), win(2, BASE + day), win(3, BASE + 2 * day)];
    expect(detectRotatingSeries(ms, BASE - 10)).toBeNull();
  });

  it("returns null for ragged (non-multiple) gaps", () => {
    // 300 then 400 — not a clean cadence.
    const ms = [win(1, BASE), win(2, BASE + 300), win(3, BASE + 700)];
    expect(detectRotatingSeries(ms, BASE - 10)).toBeNull();
  });

  it("detects a 5-minute series and finds the live window by close time", () => {
    const ms = [
      win(1, BASE + 0, "RESOLVED"),
      win(2, BASE + 300, "RESOLVED"),
      win(3, BASE + 600, "ACTIVE"),
      win(4, BASE + 900, "ACTIVE"),
    ];
    // now is inside the window that closes at +600 → [+300, +600).
    const s = detectRotatingSeries(ms, BASE + 450);
    expect(s).not.toBeNull();
    expect(s!.interval).toBe(300);
    expect(s!.live!.market_id).toBe(3);
    expect(s!.upcoming.map((m) => m.market_id)).toEqual([4]);
    // past is most-recent-first.
    expect(s!.past.map((m) => m.market_id)).toEqual([2, 1]);
  });

  it("tolerates missing windows (gaps that are integer multiples)", () => {
    // gaps 300 then 900 (3×300) — a couple of windows never synced.
    const ms = [
      win(1, BASE, "RESOLVED"),
      win(2, BASE + 300, "ACTIVE"),
      win(3, BASE + 1200, "ACTIVE"),
    ];
    const s = detectRotatingSeries(ms, BASE + 150);
    expect(s).not.toBeNull();
    expect(s!.interval).toBe(300);
    expect(s!.live!.market_id).toBe(2);
  });

  it("returns live=null when every window has ended", () => {
    const ms = [
      win(1, BASE, "RESOLVED"),
      win(2, BASE + 300, "RESOLVED"),
    ];
    const s = detectRotatingSeries(ms, BASE + 10_000);
    expect(s).not.toBeNull();
    expect(s!.live).toBeNull();
    expect(s!.past.map((m) => m.market_id)).toEqual([2, 1]);
  });

  it("treats a closed-state window as past even before its close time", () => {
    const ms = [
      win(1, BASE, "ACTIVE"),
      win(2, BASE + 300, "CLOSED"),
    ];
    // now is before either close, but window 2 is already CLOSED upstream.
    const s = detectRotatingSeries(ms, BASE - 100);
    expect(s).not.toBeNull();
    expect(s!.past.map((m) => m.market_id)).toEqual([2]);
    expect(s!.live!.market_id).toBe(1);
  });
});
