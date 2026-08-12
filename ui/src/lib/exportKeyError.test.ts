import { describe, expect, it } from "vitest";
import { exportErrorMessage } from "./exportKeyError";

const COOLDOWN_BODY = JSON.stringify({
  detail: "too many attempts — wait a moment",
});
const SIGN_IN_AGAIN_BODY = JSON.stringify({
  detail: "sign in again to export this key",
});

describe("exportErrorMessage", () => {
  it("401: wrong or expired code", () => {
    expect(exportErrorMessage(401, "")).toBe("That code is wrong or expired.");
  });

  it("429: too many attempts", () => {
    expect(exportErrorMessage(429, "")).toBe(
      "Too many attempts. Wait a moment and try again.",
    );
  });

  it("400 + cooldown detail: too many attempts", () => {
    expect(exportErrorMessage(400, COOLDOWN_BODY)).toBe(
      "Too many attempts. Wait a moment and try again.",
    );
  });

  it("400 without the cooldown detail: sign in again, not the cooldown message", () => {
    const message = exportErrorMessage(400, SIGN_IN_AGAIN_BODY);
    expect(message).not.toMatch(/too many attempts/i);
    expect(message).toBe("Sign in again, then retry the export.");
  });

  it("503: key export unavailable, not the generic dead end", () => {
    const message = exportErrorMessage(503, "");
    expect(message).not.toBe("Failed to export private key.");
    expect(message).toMatch(/key export/i);
  });

  it("falls back to the generic message for anything else", () => {
    expect(exportErrorMessage(500, "")).toBe("Failed to export private key.");
  });
});
