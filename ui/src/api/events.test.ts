import { beforeEach, describe, expect, it, vi } from "vitest";
import { listEvents } from "./events";
import { apiFetch } from "@/api/client";
import type { GammaEvent, GammaMarket } from "@/types/gamma";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

function market(closed: boolean): GammaMarket {
  return {
    id: "7",
    conditionId: "0xabc",
    question: "Q?",
    slug: "q",
    description: "",
    groupItemTitle: null,
    outcomes: '["Yes","No"]',
    outcomePrices: '["0.5","0.5"]',
    clobTokenIds: '["1","2"]',
    active: !closed,
    closed,
    acceptingOrders: !closed,
    startDate: null,
    endDate: null,
    endDateIso: null,
    icon: null,
    image: null,
    volume: "0",
    liquidity: "0",
    bestBid: 0,
    bestAsk: 0,
    lastTradePrice: 0,
    spread: 0,
  };
}

function event(id: string, markets: GammaMarket[]): GammaEvent {
  return {
    id,
    slug: `ev-${id}`,
    title: `Event ${id}`,
    description: "",
    category: null,
    icon: null,
    image: null,
    startDate: null,
    endDate: null,
    volume: "0",
    volume24hr: "0",
    liquidity: "0",
    competitive: "0",
    markets,
  } as GammaEvent;
}

describe("listEvents", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset());

  it("hides events whose markets are ALL resolved (closed)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce([
      event("1", [market(true), market(true)]), // fully resolved -> hidden
      event("2", [market(true), market(false)]), // one live market -> shown
      event("3", [market(false)]), // live -> shown
    ]);
    const r = await listEvents({ limit: 3, offset: 0 });
    expect(r.events.map((e) => e.event.event_id)).toEqual([2, 3]);
  });

  it("advances paging in WIRE units so filtering never shifts the offset", async () => {
    // Full wire page of 2, both resolved: zero events rendered, but the next
    // offset must still be 0+2 and hasMore true — otherwise page 2 would
    // re-fetch (and duplicate) rows the filter skipped.
    vi.mocked(apiFetch).mockResolvedValueOnce([
      event("1", [market(true)]),
      event("2", [market(true)]),
    ]);
    const r = await listEvents({ limit: 2, offset: 0 });
    expect(r.events).toEqual([]);
    expect(r.nextOffset).toBe(2);
    expect(r.hasMore).toBe(true);
  });

  it("stops paging on a short wire page", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce([event("1", [market(false)])]);
    const r = await listEvents({ limit: 2, offset: 4 });
    expect(r.hasMore).toBe(false);
    expect(r.nextOffset).toBe(5);
  });

  it("hides an event with zero markets (nothing tradeable)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce([event("9", [])]);
    const r = await listEvents({ limit: 1, offset: 0 });
    expect(r.events).toEqual([]);
  });
});

describe("listEvents sort param", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset().mockResolvedValue([]));

  function requestedPath(): string {
    return String(vi.mocked(apiFetch).mock.calls[0]?.[0]);
  }

  it("serialises the sort", async () => {
    await listEvents({ limit: 20, offset: 0, sort: "liquidity" });
    expect(requestedPath()).toContain("sort=liquidity");
  });

  it("omits the sort when absent or blank, so the server picks its default", async () => {
    await listEvents({ limit: 20, offset: 0, sort: "  " });
    expect(requestedPath()).not.toContain("sort=");
    await listEvents({ limit: 20, offset: 0 });
    expect(String(vi.mocked(apiFetch).mock.calls[1]?.[0])).not.toContain("sort=");
  });

  it("keeps carrying the tag filters alongside it", async () => {
    await listEvents({
      limit: 20,
      offset: 0,
      sort: "competitive",
      tag: "politics",
      subtags: ["trump"],
    });
    const path = requestedPath();
    expect(path).toContain("sort=competitive");
    expect(path).toContain("tag=politics");
    expect(path).toContain("subtag=trump");
  });
});
