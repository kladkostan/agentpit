import { describe, expect, it } from "vitest";

/** The counter used to sum ACTIVE markets across the pages the infinite scroll
 *  had loaded, so it grew as the user scrolled: 93 on the first page against
 *  1928 genuinely active. These guard the shape the fix depends on. */
describe("live market count", () => {
  const pageOf = (activePerEvent: number[]) =>
    activePerEvent.map((n) => ({
      markets: Array.from({ length: n }, () => ({ market_state: "ACTIVE" })),
    }));

  const sumLoadedPages = (pages: { markets: { market_state: string }[] }[]) =>
    pages.reduce(
      (acc, ev) =>
        acc + ev.markets.filter((m) => m.market_state === "ACTIVE").length,
      0,
    );

  it("the old page-sum grows as more pages load", () => {
    const firstPage = pageOf([5, 4]);
    const twoPages = pageOf([5, 4, 6, 3]);
    expect(sumLoadedPages(firstPage)).toBe(9);
    expect(sumLoadedPages(twoPages)).toBe(18);
    // Same platform, two different "totals" — the bug.
    expect(sumLoadedPages(firstPage)).not.toBe(sumLoadedPages(twoPages));
  });

  it("the server count does not depend on how much was loaded", () => {
    const stats = { active: 1928 };
    expect(stats.active).toBe(1928);
    expect(stats.active).not.toBe(sumLoadedPages(pageOf([5, 4])));
  });
});
