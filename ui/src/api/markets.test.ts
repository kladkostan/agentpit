import { beforeEach, describe, expect, it, vi } from "vitest";
import { gammaToMarket, getMarket } from "./markets";
import { apiFetch } from "@/api/client";
import type { GammaMarket } from "@/types/gamma";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

const baseGamma: GammaMarket = {
  id: "7",
  conditionId: "0xabc",
  question: "Will Spain win the 2026 FIFA World Cup?",
  slug: "will-spain-win",
  description: "desc",
  groupItemTitle: "Spain",
  outcomes: '["Yes","No"]',
  outcomePrices: '["0.16","0.84"]',
  clobTokenIds: '["111","222"]',
  active: true,
  closed: false,
  acceptingOrders: true,
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

describe("gammaToMarket", () => {
  it("maps groupItemTitle to the short outcome_label", () => {
    expect(gammaToMarket(baseGamma).outcome_label).toBe("Spain");
  });

  it("leaves outcome_label null for a standalone market", () => {
    const m = gammaToMarket({ ...baseGamma, groupItemTitle: null });
    expect(m.outcome_label).toBeNull();
  });
});

describe("getMarket", () => {
  beforeEach(() => vi.mocked(apiFetch).mockReset());

  it("fetches by integer id via /markets/:id", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(baseGamma);
    const m = await getMarket(11);
    expect(apiFetch).toHaveBeenCalledWith("/markets/11");
    expect(m.market_id).toBe(7);
  });

  it("treats a numeric-string id as an id (route params arrive as strings)", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(baseGamma);
    await getMarket("11");
    expect(apiFetch).toHaveBeenCalledWith("/markets/11");
  });

  it("resolves a non-numeric slug via /markets?slug= and takes the first match", async () => {
    // Positions identify a market by slug (no integer id), so the detail
    // lookup must accept a slug — regression for the 422 dead-link bug.
    vi.mocked(apiFetch).mockResolvedValueOnce([baseGamma]);
    const m = await getMarket("will-france-win-the-2026-fifa-world-cup-924");
    expect(apiFetch).toHaveBeenCalledWith(
      "/markets?slug=will-france-win-the-2026-fifa-world-cup-924",
    );
    expect(m.question).toBe(baseGamma.question);
  });

  it("throws a clear error when no market matches the slug", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce([]);
    await expect(getMarket("nonexistent-slug")).rejects.toThrow(/not found/i);
  });
});
