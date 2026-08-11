import { describe, expect, it } from "vitest";
import { positionBucket, unclaimedTotal } from "./positionBuckets";

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
