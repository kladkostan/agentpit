import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import {
  canResend,
  isCompleteCode,
  normaliseCode,
  RESEND_COOLDOWN_SECONDS,
  refreshFailureEndsSession,
  resendSecondsLeft,
  sendCodeErrorMessage,
  signInErrorMessage,
  statusOf,
} from "./codeFlow";

const SENT_AT = 1_700_000_000_000;

describe("normaliseCode", () => {
  it("keeps a plain six-digit code as it is", () => {
    expect(normaliseCode("515627")).toBe("515627");
  });

  it("strips the space people paste from the mail body", () => {
    expect(normaliseCode("515 627")).toBe("515627");
  });

  it("strips the zero-width characters mail clients wrap codes in", () => {
    // A real paste out of a rendered HTML mail carries U+200B/U+FEFF around
    // the digits; without this the field silently holds a 7+ character value
    // that can never be complete.
    expect(normaliseCode("\u200B515\u200B627\uFEFF")).toBe("515627");
  });

  it("drops anything that is not a digit rather than rejecting the paste", () => {
    expect(normaliseCode("code: 515-627.")).toBe("515627");
  });

  it("never grows past six digits, so a doubled paste cannot 422", () => {
    expect(normaliseCode("515627515627")).toBe("515627");
  });

  it("returns empty for a value with no digits at all", () => {
    expect(normaliseCode("   ")).toBe("");
  });
});

describe("isCompleteCode", () => {
  it("accepts exactly six digits", () => {
    expect(isCompleteCode("515627")).toBe(true);
  });

  it("rejects five digits — the backend answers 422, not 401", () => {
    expect(isCompleteCode("51562")).toBe(false);
  });

  it("rejects seven digits", () => {
    expect(isCompleteCode("5156277")).toBe(false);
  });

  it("rejects an empty value", () => {
    expect(isCompleteCode("")).toBe(false);
  });

  it("rejects six characters that are not all digits", () => {
    expect(isCompleteCode("51562a")).toBe(false);
  });
});

describe("resendSecondsLeft", () => {
  it("is the full cooldown the instant the code goes out", () => {
    expect(resendSecondsLeft(SENT_AT, SENT_AT)).toBe(RESEND_COOLDOWN_SECONDS);
  });

  it("counts down while the cooldown runs", () => {
    expect(resendSecondsLeft(SENT_AT, SENT_AT + 15_000)).toBe(
      RESEND_COOLDOWN_SECONDS - 15,
    );
  });

  it("rounds a part-second up, so it never shows 0 while still blocked", () => {
    expect(resendSecondsLeft(SENT_AT, SENT_AT + 59_500)).toBe(1);
  });

  it("is 0 exactly at the end of the cooldown", () => {
    expect(
      resendSecondsLeft(SENT_AT, SENT_AT + RESEND_COOLDOWN_SECONDS * 1000),
    ).toBe(0);
  });

  it("never goes negative long after the code was sent", () => {
    expect(resendSecondsLeft(SENT_AT, SENT_AT + 3_600_000)).toBe(0);
  });

  it("is 0 before any code has been sent", () => {
    expect(resendSecondsLeft(null, SENT_AT)).toBe(0);
  });

  it("is 0 for a clock that jumped backwards rather than a huge countdown", () => {
    // A machine that resyncs its clock mid-flow must not lock the resend
    // button for hours.
    expect(resendSecondsLeft(SENT_AT, SENT_AT - 3_600_000)).toBe(0);
  });
});

describe("canResend", () => {
  it("is false while the countdown runs", () => {
    expect(canResend(SENT_AT, SENT_AT + 1_000)).toBe(false);
  });

  it("is false at the very moment of sending", () => {
    expect(canResend(SENT_AT, SENT_AT)).toBe(false);
  });

  it("is true once the cooldown has elapsed", () => {
    expect(canResend(SENT_AT, SENT_AT + RESEND_COOLDOWN_SECONDS * 1000)).toBe(
      true,
    );
  });

  it("is true before any code has been sent", () => {
    expect(canResend(null, SENT_AT)).toBe(true);
  });
});

describe("statusOf", () => {
  it("reads the status off an ApiError", () => {
    expect(statusOf(new ApiError(401, "", "nope"))).toBe(401);
  });

  it("is 0 for a network failure, which lands on the generic copy", () => {
    expect(statusOf(new TypeError("Failed to fetch"))).toBe(0);
    expect(signInErrorMessage(statusOf(new TypeError("Failed to fetch")))).toBe(
      "Could not sign you in. Try again in a moment.",
    );
  });

  it("is 0 for a thrown non-error", () => {
    expect(statusOf("boom")).toBe(0);
  });
});

describe("signInErrorMessage", () => {
  it("401 does not distinguish a wrong code from an expired one", () => {
    // The two are one failure: telling them apart tells an attacker which
    // codes existed, and tells the user nothing they can act on differently.
    const message = signInErrorMessage(401);
    expect(message).toBe("That code is wrong or expired.");
  });

  it("429 says to wait rather than repeating the wrong-code copy", () => {
    const message = signInErrorMessage(429);
    expect(message).not.toBe(signInErrorMessage(401));
    expect(message).toMatch(/too many|wait/i);
  });

  it("503 explains the feature is off rather than blaming the code", () => {
    // `POST /auth/session` answers 503 when WorkOS is not configured. Showing
    // "that code is wrong" there sends the user round the loop forever.
    const message = signInErrorMessage(503);
    expect(message).not.toBe(signInErrorMessage(401));
    expect(message).toMatch(/sign-in|available/i);
  });

  it("falls back to a generic message for anything else", () => {
    expect(signInErrorMessage(500)).toBe(
      "Could not sign you in. Try again in a moment.",
    );
    expect(signInErrorMessage(0)).toBe(
      "Could not sign you in. Try again in a moment.",
    );
  });
});

describe("sendCodeErrorMessage", () => {
  it("never says whether the address has an account", () => {
    // `POST /auth/code` answers 202 for known and unknown addresses alike so
    // the reply is not an existence oracle. Copy that leaked it would undo
    // the whole reason the endpoint is shaped that way.
    for (const status of [0, 400, 401, 404, 422, 429, 500, 503]) {
      const message = sendCodeErrorMessage(status);
      expect(message).not.toMatch(/account|registered|exist|unknown/i);
    }
  });

  it("429 says to wait", () => {
    expect(sendCodeErrorMessage(429)).toMatch(/too many|wait/i);
  });

  it("422 points at the address, the one thing the user can fix", () => {
    expect(sendCodeErrorMessage(422)).toBe(
      "Please enter a valid email address.",
    );
  });

  it("503 explains the feature is off", () => {
    expect(sendCodeErrorMessage(503)).toMatch(/sign-in|available/i);
  });

  it("falls back to a generic message for anything else", () => {
    expect(sendCodeErrorMessage(500)).toBe(
      "Could not send the code. Try again in a moment.",
    );
  });
});

describe("refreshFailureEndsSession", () => {
  it("ends the session when the server rejects the refresh token", () => {
    expect(refreshFailureEndsSession(401)).toBe(true);
  });

  it("keeps the session through an outage", () => {
    // 503 is the status the backend added specifically to mean "this is our
    // problem, not your credential". Logging out on it deletes a refresh
    // token that was never invalid, and WorkOS does not rotate them, so the
    // copy in storage is the only copy.
    expect(refreshFailureEndsSession(503)).toBe(false);
    expect(refreshFailureEndsSession(500)).toBe(false);
    expect(refreshFailureEndsSession(502)).toBe(false);
  });

  it("keeps the session when the request never reached the server", () => {
    // statusOf() answers 0 for a dropped connection or an offline browser.
    expect(refreshFailureEndsSession(0)).toBe(false);
  });

  it("keeps the session on a 400", () => {
    // A failed on-chain onboarding retry answers 400. It is a bad minute for
    // the chain, not evidence about the credential.
    expect(refreshFailureEndsSession(400)).toBe(false);
  });
});
