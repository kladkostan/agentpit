import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  describeActivity,
  listActivity,
  marketHref,
  type ActivityEntry,
} from "./activity";
import { apiFetch } from "@/api/client";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

function entry(over: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    timestamp: 1786042311,
    conditionId: "0xabc",
    type: "TRADE",
    size: 20,
    usdcSize: 10.2,
    price: 0.51,
    side: "BUY",
    title: "Will the Fed hold?",
    slug: "fed-hold",
    eventSlug: "fed-decision-in-september",
    icon: "",
    outcome: "Yes",
    // `exactOptionalPropertyTypes` turns every key of the Partial override into
    // an optional one, so the spread widens the result away from ActivityEntry.
    // Same cast the neighbouring events.test.ts factory uses.
    ...over,
  } as ActivityEntry;
}

describe("listActivity", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset().mockResolvedValue([]));

  it("requests /activity for the given address", async () => {
    await listActivity("0xUser");
    expect(String(vi.mocked(apiFetch).mock.calls[0]?.[0])).toContain(
      "/activity?user=0xUser",
    );
  });

  it("encodes the address and passes the limit", async () => {
    await listActivity("0x A&B", 5);
    const path = String(vi.mocked(apiFetch).mock.calls[0]?.[0]);
    expect(path).toContain("user=0x%20A%26B");
    expect(path).toContain("limit=5");
  });

  it("returns the entries unchanged", async () => {
    const wire = [entry({ side: "SELL" })];
    vi.mocked(apiFetch).mockResolvedValueOnce(wire);
    await expect(listActivity("0xUser")).resolves.toEqual(wire);
  });
});

describe("describeActivity", () => {
  it("distinguishes a buy from a sell", () => {
    // The whole point of the tab: a sale must be visible as a sale. The old
    // Activity list rendered open positions, so a sold-out market showed
    // nothing at all.
    expect(describeActivity(entry({ side: "BUY" }))).toBe("Bought");
    expect(describeActivity(entry({ side: "SELL" }))).toBe("Sold");
  });

  it("names the non-trade position changes by type, not by side", () => {
    expect(describeActivity(entry({ type: "SPLIT", side: "" }))).toBe("Split");
    expect(describeActivity(entry({ type: "MERGE", side: "" }))).toBe("Merged");
    expect(describeActivity(entry({ type: "REDEEM", side: "" }))).toBe(
      "Redeemed",
    );
  });

  it("falls back to the raw type for anything unrecognised", () => {
    expect(describeActivity(entry({ type: "CONVERT" }))).toBe("CONVERT");
    expect(describeActivity(entry({ type: "" }))).toBe("Activity");
  });
});

describe("marketHref", () => {
  it("links at the event that groups the market", () => {
    // A market is one outcome inside a question; the bare market page hides
    // the siblings the user was choosing between.
    expect(marketHref(entry())).toBe("/events/fed-decision-in-september");
  });

  it("falls back to the market when it belongs to no event", () => {
    expect(marketHref(entry({ eventSlug: "" }))).toBe("/markets/fed-hold");
  });

  it("treats a blank or missing event slug as absent", () => {
    expect(marketHref(entry({ eventSlug: "   " }))).toBe("/markets/fed-hold");
    expect(marketHref({ slug: "fed-hold" })).toBe("/markets/fed-hold");
  });
});
