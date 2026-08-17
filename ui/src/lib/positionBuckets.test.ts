import { describe, expect, it } from "vitest";
import {
  effectivePositionFilter,
  positionBucket,
  unclaimedTotal,
} from "./positionBuckets";

describe("positionBucket", () => {
  it("puts a won-but-unclaimed position in its own bucket", () => {
    expect(positionBucket({ redeemable: true })).toBe("unclaimed");
  });

  it("leaves everything else among the active positions", () => {
    expect(positionBucket({ redeemable: false })).toBe("active");
  });
});

describe("unclaimedTotal", () => {
  it("adds up only what can be claimed", () => {
    expect(
      unclaimedTotal([
        { redeemable: true, currentValue: 100 },
        { redeemable: true, currentValue: 40.5 },
        { redeemable: false, currentValue: 999 },
      ]),
    ).toBe(140.5);
  });

  it("is zero when there is nothing to claim", () => {
    expect(unclaimedTotal([{ redeemable: false, currentValue: 999 }])).toBe(0);
  });

  it("is zero for an empty list", () => {
    expect(unclaimedTotal([])).toBe(0);
  });
});

describe("effectivePositionFilter", () => {
  it("falls back to active when unclaimed is selected but there is nothing left to claim", () => {
    expect(effectivePositionFilter("unclaimed", 0)).toBe("active");
  });

  it("stays on unclaimed while there is still something to claim", () => {
    expect(effectivePositionFilter("unclaimed", 40.5)).toBe("unclaimed");
  });

  it("leaves active alone regardless of the unclaimed total", () => {
    expect(effectivePositionFilter("active", 0)).toBe("active");
    expect(effectivePositionFilter("active", 100)).toBe("active");
  });

  it("leaves closed alone regardless of the unclaimed total", () => {
    expect(effectivePositionFilter("closed", 0)).toBe("closed");
    expect(effectivePositionFilter("closed", 100)).toBe("closed");
  });
});
