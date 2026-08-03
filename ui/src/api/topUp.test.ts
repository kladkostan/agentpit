import { describe, expect, it } from "vitest";
import { topUpButtonState, topUpLabel } from "./portfolio";

const NOW = 1_700_000_000;

describe("topUpLabel", () => {
  it("offers the top-up when the cooldown has passed", () => {
    expect(topUpLabel(NOW - 1, NOW)).toBe("Top up to $100k");
  });

  it("counts down in hours while the cooldown runs", () => {
    expect(topUpLabel(NOW + 3 * 3600, NOW)).toBe("Available in 3h");
  });

  it("rounds a part-hour up rather than showing 0h", () => {
    expect(topUpLabel(NOW + 60, NOW)).toBe("Available in 1h");
  });
});

describe("topUpButtonState", () => {
  // Regression: an earlier draft derived nextAllowedAt from the mutation's
  // `.data`, which is undefined until the user clicks — so on page load,
  // even mid-cooldown, the button always rendered enabled. The fix is a
  // separate GET-backed status query that's fetched on load. This asserts
  // the *fetched status alone*, with no mutation ever having run, is enough
  // to disable the button — which the broken version could never do, since
  // it had no status data to read at all.
  it("disables the button from the fetched status, with no click yet", () => {
    const state = topUpButtonState({ nextAllowedAt: NOW + 3600 }, false, NOW);
    expect(state.disabled).toBe(true);
    expect(state.label).toBe("Available in 1h");
  });

  it("enables the button once the fetched status says the cooldown passed", () => {
    const state = topUpButtonState({ nextAllowedAt: NOW - 1 }, false, NOW);
    expect(state.disabled).toBe(false);
    expect(state.label).toBe("Top up to $100k");
  });

  it("stays disabled while the mutation is in flight, regardless of status", () => {
    const state = topUpButtonState({ nextAllowedAt: NOW - 1 }, true, NOW);
    expect(state.disabled).toBe(true);
    expect(state.label).toBe("Topping up…");
  });

  it("treats a not-yet-loaded status as eligible rather than blocking forever", () => {
    const state = topUpButtonState(undefined, false, NOW);
    expect(state.disabled).toBe(false);
    expect(state.label).toBe("Top up to $100k");
  });
});
