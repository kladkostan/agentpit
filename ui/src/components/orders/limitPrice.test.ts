import { describe, expect, it } from "vitest";
import {
  MAX_CENTS,
  MIN_CENTS,
  STEP_CENTS,
  normaliseLimitCents,
  stepLimitCents,
} from "./limitPrice";

describe("normaliseLimitCents", () => {
  it("passes the one and two digit prices through untouched", () => {
    expect(normaliseLimitCents("5", "")).toBe("5");
    expect(normaliseLimitCents("50", "5")).toBe("50");
  });

  it("turns the third digit into the decimal", () => {
    // Typing 1, 1, 5 means 11.5¢. Read as an integer it would be 115¢,
    // a price above a dollar for something that can only ever pay one.
    expect(normaliseLimitCents("115", "11")).toBe("11.5");
  });

  it("only shifts a digit that was typed onto the end", () => {
    // A digit dropped in front of "99" arrives as "199" too, and shifting
    // that would answer 19.9 — promoting the second 9, which the trader
    // never touched, into the tenths. Refuse the keystroke instead.
    expect(normaliseLimitCents("199", "99")).toBe("99");
    expect(normaliseLimitCents("919", "99")).toBe("99");
    expect(normaliseLimitCents("550", "50")).toBe("50");
    // The same three characters, appended, still mean what they meant.
    expect(normaliseLimitCents("991", "99")).toBe("99.1");
  });

  it("refuses a fourth digit instead of reshaping the number", () => {
    expect(normaliseLimitCents("1157", "11.5")).toBe("11.5");
  });

  it("holds the top of the grid and nothing above it", () => {
    // 99.9¢ is $0.999, the largest price the server's 0.001 tick leaves
    // inside (0, 1); 99.95¢ would snap to 1.000 and come back a 422.
    expect(normaliseLimitCents("999", "99")).toBe("99.9");
    expect(normaliseLimitCents("99.95", "99.9")).toBe("99.9");
  });

  it("has no way to express the huge numbers the field used to accept", () => {
    // The regression this exists for: the field would happily show 10000¢
    // and then go quiet, because a $100 price fails the preview's own
    // sanity test and the ticket simply renders no total.
    expect(normaliseLimitCents("10000", "50")).toBe("50");
    expect(normaliseLimitCents("1000", "50")).toBe("50");
  });

  it("keeps a decimal the user typed themselves", () => {
    // Below 10¢ the third-digit rule never fires, so the point is the only
    // way to reach 5.5¢ — and it has to work.
    expect(normaliseLimitCents("5.5", "5.")).toBe("5.5");
    expect(normaliseLimitCents("5.", "5")).toBe("5.");
  });

  it("reads a leading zero as the start of a sub-cent price", () => {
    expect(normaliseLimitCents("0", "")).toBe("0");
    expect(normaliseLimitCents("0.5", "0.")).toBe("0.5");
    expect(normaliseLimitCents(".5", "")).toBe("0.5");
  });

  it("drops a leading zero that is only padding", () => {
    expect(normaliseLimitCents("05", "0")).toBe("5");
    expect(normaliseLimitCents("00", "0")).toBe("0");
  });

  it("lets the field be emptied", () => {
    // Clearing to type a fresh price must be possible; the ticket already
    // treats an unparseable price as no order.
    expect(normaliseLimitCents("", "50")).toBe("");
  });

  it("refuses anything that is not a number", () => {
    expect(normaliseLimitCents("5o", "5")).toBe("5");
    expect(normaliseLimitCents("-5", "5")).toBe("5");
    expect(normaliseLimitCents("1e2", "1")).toBe("1");
    expect(normaliseLimitCents("1.2.3", "1.2")).toBe("1.2");
  });

  it("takes the comma decimal separator half the world types", () => {
    expect(normaliseLimitCents("11,5", "11")).toBe("11.5");
  });

  it("survives a paste with surrounding whitespace", () => {
    expect(normaliseLimitCents("  42 ", "50")).toBe("42");
  });
});

describe("stepLimitCents", () => {
  it("moves by one tick, the finest price the grid has", () => {
    expect(stepLimitCents("50", STEP_CENTS)).toBe("50.1");
    expect(stepLimitCents("50", -STEP_CENTS)).toBe("49.9");
  });

  it("keeps the tenth the user typed", () => {
    // The stepper used to round to whole cents, so one press of + on a
    // hand-typed 11.5 threw the decimal away.
    expect(stepLimitCents("11.5", STEP_CENTS)).toBe("11.6");
    expect(stepLimitCents("11.5", -STEP_CENTS)).toBe("11.4");
  });

  it("stops at the ends of the grid", () => {
    expect(stepLimitCents("99.9", STEP_CENTS)).toBe(String(MAX_CENTS));
    expect(stepLimitCents("0.1", -STEP_CENTS)).toBe(String(MIN_CENTS));
  });

  it("does not leave binary float dust in the field", () => {
    // 0.1 + 0.2 is 0.30000000000000004 in doubles, and that would be the
    // string the field shows.
    expect(stepLimitCents("0.1", STEP_CENTS)).toBe("0.2");
    expect(stepLimitCents("0.2", STEP_CENTS)).toBe("0.3");
    expect(stepLimitCents("70.1", -STEP_CENTS)).toBe("70");
  });

  it("starts from the middle when the field holds no number", () => {
    expect(stepLimitCents("", STEP_CENTS)).toBe("50.1");
    expect(stepLimitCents(".", -STEP_CENTS)).toBe("49.9");
  });

  it("reads a half-typed price as the number in front of the point", () => {
    expect(stepLimitCents("11.", STEP_CENTS)).toBe("11.1");
  });

  it("takes any tick count the caller asks for", () => {
    // The buttons send one tick, but nothing in here assumes that.
    expect(stepLimitCents("50", 1)).toBe("51");
    expect(stepLimitCents("50", -10 * STEP_CENTS)).toBe("49");
  });
});
