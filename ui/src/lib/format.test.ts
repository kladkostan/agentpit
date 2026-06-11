import { describe, expect, it } from "vitest";
import { formatProbabilityPct, parseVolume } from "./format";

describe("parseVolume", () => {
  it("returns null for absent, zero, or unparseable input", () => {
    expect(parseVolume(null)).toBeNull();
    expect(parseVolume(undefined)).toBeNull();
    expect(parseVolume("")).toBeNull();
    expect(parseVolume("0")).toBeNull();
    expect(parseVolume("nope")).toBeNull();
  });

  it("parses a positive numeric string", () => {
    expect(parseVolume("14646954.7")).toBeCloseTo(14646954.7);
    expect(parseVolume("850")).toBe(850);
  });
});

describe("formatProbabilityPct", () => {
  it("renders an em dash for a null mid", () => {
    expect(formatProbabilityPct(null)).toBe("—");
  });

  it("shows '<1' for a non-zero probability under 1%", () => {
    // 0.9¢ used to round down to a misleading "0".
    expect(formatProbabilityPct(0.009)).toBe("<1");
    expect(formatProbabilityPct(0.001)).toBe("<1");
    expect(formatProbabilityPct(0.005)).toBe("<1");
  });

  it("shows '0' only for an exactly-zero (or empty) probability", () => {
    expect(formatProbabilityPct(0)).toBe("0");
  });

  it("rounds 1% and above to the nearest whole percent", () => {
    expect(formatProbabilityPct(0.01)).toBe("1");
    expect(formatProbabilityPct(0.184)).toBe("18");
    expect(formatProbabilityPct(0.995)).toBe("100");
  });
});
