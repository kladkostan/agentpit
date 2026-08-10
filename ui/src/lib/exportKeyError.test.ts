import { describe, expect, it } from "vitest";
import { exportErrorMessage } from "./exportKeyError";

const COOLDOWN_BODY = JSON.stringify({
  detail: "too many attempts — wait a moment",
});
const WRONG_FACTOR_PASSWORD_BODY = JSON.stringify({
  detail: "this account exports with its password",
});
const WRONG_FACTOR_GOOGLE_BODY = JSON.stringify({
  detail: "this account exports with Google",
});

describe("exportErrorMessage", () => {
  it("401 + password account: wrong password", () => {
    expect(exportErrorMessage(401, true, "")).toBe("Incorrect password.");
  });

  it("401 + Google account: wrong Google account, not 'incorrect password'", () => {
    const message = exportErrorMessage(401, false, "");
    expect(message).not.toMatch(/password/i);
    expect(message).toMatch(/google/i);
  });

  it("400 + cooldown detail: too many attempts", () => {
    expect(exportErrorMessage(400, true, COOLDOWN_BODY)).toBe(
      "Too many attempts. Wait a moment and try again.",
    );
    expect(exportErrorMessage(400, false, COOLDOWN_BODY)).toBe(
      "Too many attempts. Wait a moment and try again.",
    );
  });

  it("400 + wrong-factor detail: not the cooldown message, regardless of which factor", () => {
    const passwordSide = exportErrorMessage(400, true, WRONG_FACTOR_GOOGLE_BODY);
    const googleSide = exportErrorMessage(400, false, WRONG_FACTOR_PASSWORD_BODY);
    expect(passwordSide).not.toMatch(/too many attempts/i);
    expect(googleSide).not.toMatch(/too many attempts/i);
  });

  it("503: explains Google sign-in is unavailable rather than the generic dead end", () => {
    const message = exportErrorMessage(503, false, "");
    expect(message).not.toBe("Failed to export private key.");
    expect(message).toMatch(/google/i);
  });

  it("falls back to the generic message for anything else", () => {
    expect(exportErrorMessage(500, true, "")).toBe(
      "Failed to export private key.",
    );
  });
});
