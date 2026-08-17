import { describe, expect, it } from "vitest";
import { claimErrorMessage } from "./claimError";

const ADDRESS = "0x933B442e9A78e3C3a567B86ee595Eb9BcEb15215";

describe("claimErrorMessage", () => {
  it("402: tells the user what's missing and where to send it", () => {
    const message = claimErrorMessage(402, ADDRESS);
    expect(message).toMatch(/credits/i);
    expect(message).toContain("0x933B…5215");
  });

  it("402: does not print the raw 42-character address", () => {
    // Long enough to wrap awkwardly in a toast -- the app shows addresses
    // short everywhere else (profile header, Settings).
    expect(claimErrorMessage(402, ADDRESS)).not.toContain(ADDRESS);
  });

  it("falls back to the generic message for anything else", () => {
    expect(claimErrorMessage(400, ADDRESS)).toBe("Failed to claim.");
    expect(claimErrorMessage(500, ADDRESS)).toBe("Failed to claim.");
    expect(claimErrorMessage(undefined, ADDRESS)).toBe("Failed to claim.");
  });
});
