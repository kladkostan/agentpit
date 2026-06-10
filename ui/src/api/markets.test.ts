import { describe, expect, it } from "vitest";
import { gammaToMarket } from "./markets";
import type { GammaMarket } from "@/types/gamma";

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
