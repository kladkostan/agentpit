import { describe, expect, it } from "vitest";
import {
  formatPnlPct,
  shortAddress,
  formatProbabilityPct,
  formatSignedUsd,
  parseVolume,
  relativeTime,
  volumeStat,
} from "./format";

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

describe("formatSignedUsd", () => {
  it("prefixes a positive amount with +", () => {
    expect(formatSignedUsd(84.2)).toBe("+$84.20");
  });

  it("prefixes a negative amount with -", () => {
    expect(formatSignedUsd(-210.8)).toBe("-$210.80");
  });

  it("renders zero without a sign", () => {
    expect(formatSignedUsd(0)).toBe("$0.00");
  });
});

describe("relativeTime", () => {
  it("renders seconds under a minute", () => {
    expect(relativeTime(42)).toBe("42s");
  });

  it("renders whole minutes under an hour", () => {
    expect(relativeTime(5 * 60 + 30)).toBe("5m");
  });

  it("renders whole hours under a day", () => {
    expect(relativeTime(2 * 3600 + 59 * 60)).toBe("2h");
  });

  it("renders whole days from 24h up", () => {
    expect(relativeTime(3 * 86_400 + 5)).toBe("3d");
  });

  it("clamps negative input (clock skew) to 0s", () => {
    expect(relativeTime(-7)).toBe("0s");
  });
});

describe("volumeStat", () => {
  it("shows the 24h figure when the list is ranked by it", () => {
    // Under "24hr Volume" the all-time number contradicts the order the card
    // sits in: $16.2M above $12.0M above $1.4M, in a list sorted by the day.
    expect(volumeStat(16_234_630, 1_566_477, "24h")).toEqual({
      value: 1_566_477,
      label: "24h vol",
    });
  });

  it("falls back to all-time when a 24h figure is asked for and missing", () => {
    expect(volumeStat(8_068_246, null, "24h")).toEqual({
      value: 8_068_246,
      label: "vol",
    });
  });

  it("prefers the all-time figure", () => {
    expect(volumeStat(8_068_246, 3_341_364)).toEqual({
      value: 8_068_246,
      label: "vol",
    });
  });

  it("falls back to 24h, labelled as 24h, when all-time is missing", () => {
    // 545 of 962 production events had exactly this shape: they had dropped out
    // of the synced top-N, so only the older 24h capture survived. Dropping the
    // line for them would have blanked most of the grid.
    expect(volumeStat(null, 3_341_364)).toEqual({
      value: 3_341_364,
      label: "24h vol",
    });
  });

  it("is null only when neither figure exists", () => {
    expect(volumeStat(null, null)).toBeNull();
  });

  it("treats a real zero as a figure, not as missing", () => {
    expect(volumeStat(0, 500)).toEqual({ value: 0, label: "vol" });
  });
});

describe("formatPnlPct", () => {
  it("keeps one decimal so the percent agrees with the dollars beside it", () => {
    // $0.30 on a $9.20 cost. "3%" implied $9.48 against a real $9.50.
    expect(formatPnlPct(3.2608695652173796)).toBe("3.3");
  });

  it("drops a trailing .0 from a clean value", () => {
    expect(formatPnlPct(25)).toBe("25");
    expect(formatPnlPct(-20)).toBe("-20");
  });

  it("preserves the sign", () => {
    expect(formatPnlPct(-21.875)).toBe("-21.9");
  });

  it("rounds half away from zero at the tenth", () => {
    expect(formatPnlPct(6.25)).toBe("6.3");
  });

  it("returns 0 for a non-finite input", () => {
    // cashPnl / 0 cost is Infinity; the row must still render.
    expect(formatPnlPct(Number.POSITIVE_INFINITY)).toBe("0");
    expect(formatPnlPct(Number.NaN)).toBe("0");
  });
});

describe("shortAddress", () => {
  it("keeps both ends so the account stays recognisable", () => {
    expect(shortAddress("0x933B442e9A78e3C3a567B86ee595Eb9BcEb15215")).toBe(
      "0x933B…5215",
    );
  });

  it("preserves case — addresses are checksummed, and lowercasing loses that", () => {
    expect(shortAddress("0xAbCdEf1234567890aaaa")).toBe("0xAbCd…aaaa");
  });

  it("passes through anything too short to be worth truncating", () => {
    expect(shortAddress("0x1234")).toBe("0x1234");
    expect(shortAddress("")).toBe("");
  });
});
