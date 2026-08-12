import { describe, expect, it } from "vitest";
import {
  exportErrorMessage,
  sendExportCodeErrorMessage,
} from "./exportKeyError";

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

describe("sendExportCodeErrorMessage", () => {
  it("401: the session died, not a mistyped code", () => {
    // Nothing has been typed when this request is sent — it carries only the
    // bearer token — and it runs without skipAuthEvent, so this 401 also logs
    // the user out. `exportErrorMessage` says the code was wrong here, which
    // was the bug.
    const message = sendExportCodeErrorMessage(401);
    expect(message).not.toBe(exportErrorMessage(401, ""));
    expect(message).not.toMatch(/code is wrong/i);
    expect(message).toMatch(/session expired/i);
  });

  it("429: too many attempts", () => {
    expect(sendExportCodeErrorMessage(429)).toBe(
      "Too many attempts. Wait a moment and try again.",
    );
  });

  it("503: key export unavailable", () => {
    expect(sendExportCodeErrorMessage(503)).toBe(
      "Key export isn't available right now. Try again later.",
    );
  });

  it("falls back to a send-shaped message, not an export-shaped one", () => {
    // The export never got as far as being attempted, so "Failed to export
    // private key" would describe the wrong step.
    for (const status of [500, 0]) {
      const message = sendExportCodeErrorMessage(status);
      expect(message).toBe("Could not send the code. Try again in a moment.");
    }
  });
});
