import { describe, expect, it } from "vitest";
import { STATE_TONE, eventState } from "./marketState";
import type { Market, MarketState } from "@/types/market";

const m = (market_state: MarketState) => ({ market_state }) as Market;

describe("eventState", () => {
  it("is ACTIVE when any market is active", () => {
    expect(eventState([m("CLOSED"), m("ACTIVE"), m("RESOLVED")])).toBe("ACTIVE");
    expect(eventState([m("ACTIVE")])).toBe("ACTIVE");
  });

  it("agrees with the grid's live rule", () => {
    // The grid's "Active" filter and the live counter both ask
    // `markets.some(m => m.market_state === "ACTIVE")`. An event the grid calls
    // live must not wear a different badge.
    const markets = [m("CLOSED"), m("ACTIVE")];
    const gridSaysLive = markets.some((x) => x.market_state === "ACTIVE");
    expect(gridSaysLive).toBe(true);
    expect(eventState(markets)).toBe("ACTIVE");
  });

  it("falls back through the precedence when nothing is active", () => {
    expect(eventState([m("CLOSED"), m("DRAFT")])).toBe("DRAFT");
    expect(eventState([m("CLOSED"), m("RESOLVED")])).toBe("RESOLVED");
    expect(eventState([m("CLOSED"), m("CANCELLED")])).toBe("CANCELLED");
    expect(eventState([m("CLOSED")])).toBe("CLOSED");
  });

  it("reads an empty event as CLOSED", () => {
    expect(eventState([])).toBe("CLOSED");
  });
});

describe("STATE_TONE", () => {
  it("covers every state so a badge can never render unstyled", () => {
    const states: MarketState[] = [
      "DRAFT",
      "ACTIVE",
      "CLOSED",
      "RESOLVED",
      "CANCELLED",
    ];
    for (const s of states) {
      expect(STATE_TONE[s].dot).toBeTruthy();
      expect(STATE_TONE[s].label).toBeTruthy();
    }
  });
});
