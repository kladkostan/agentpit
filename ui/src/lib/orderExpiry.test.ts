import { describe, expect, it } from "vitest";
import { expiryForLabel, isExpiryDisabled } from "@/lib/orderExpiry";

const NOON = Date.parse("2026-08-17T12:00:00");

describe("expiryForLabel", () => {
  it("sends never as a GTC with a zero expiration", () => {
    // Zero is Polymarket's own convention for "no timer", and the API
    // refuses a non-zero expiration on anything but a GTD.
    expect(expiryForLabel("Never", NOON)).toEqual({
      order_type: "GTC",
      expiration: 0,
    });
  });

  it("adds the grace minute so an hour means an hour", () => {
    // The server treats an order as dead a minute before its stamp, so a
    // client asking for N seconds sends now + 60 + N. Without the 60 the
    // user gets 59 minutes and no explanation.
    const { order_type, expiration } = expiryForLabel("1h", NOON);
    expect(order_type).toBe("GTD");
    expect(expiration).toBe(Math.floor(NOON / 1000) + 60 + 3600);
  });

  it("clears the three-minute floor on the shortest option", () => {
    const { expiration } = expiryForLabel("5m", NOON);
    expect(expiration - Math.floor(NOON / 1000)).toBeGreaterThanOrEqual(180);
  });

  it("ends the day at the next local midnight", () => {
    const { expiration } = expiryForLabel("End of day", NOON);
    const midnight = new Date(NOON);
    midnight.setHours(24, 0, 0, 0);
    expect(expiration).toBe(Math.floor(midnight.getTime() / 1000) + 60);
  });

  it("does not lose a second when now falls mid-second", () => {
    // Every other "End of day" case above lands on an exact second, which
    // hides a double-floor bug: flooring the gap to midnight AND flooring
    // now separately (when this lifetime is added back to now) rounds off
    // now's millisecond remainder twice, landing ~1s before midnight.
    // `midnight` itself is always exact -- setHours(24, 0, 0, 0) zeroes the
    // sub-second fields regardless of `now` -- so the expected expiration is
    // the same "midnight + grace" formula as the exact-second case above.
    const nowMs = NOON + 328;
    const { expiration } = expiryForLabel("End of day", nowMs);
    const midnight = new Date(nowMs);
    midnight.setHours(24, 0, 0, 0);
    expect(expiration).toBe(Math.floor(midnight.getTime() / 1000) + 60);
  });
});

describe("isExpiryDisabled", () => {
  it("disables end of day when midnight is inside the floor", () => {
    // Sending it would be rejected with a 400 the user cannot act on.
    const almost = new Date(NOON);
    almost.setHours(23, 59, 0, 0);
    expect(isExpiryDisabled("End of day", almost.getTime())).toBe(true);
  });

  it("leaves it alone the rest of the day", () => {
    expect(isExpiryDisabled("End of day", NOON)).toBe(false);
    expect(isExpiryDisabled("1h", NOON)).toBe(false);
    expect(isExpiryDisabled("Never", NOON)).toBe(false);
  });
});
