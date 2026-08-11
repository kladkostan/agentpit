/**
 * The decisions behind the two-step sign-in dialog (address, then code).
 *
 * `ui/` vitest is node-env with no `@testing-library/react`, so `AuthDialog`
 * itself cannot be render-tested. Everything here is therefore a pure function
 * the dialog only reads from — keep it that way, or the decision stops being
 * covered the moment it moves into the component.
 */

import { ApiError } from "@/api/client";

/** Codes WorkOS mails are six digits — the backend rejects anything else 422. */
export const CODE_LENGTH = 6;

/**
 * How long the dialog blocks a resend. Not a security control — WorkOS rate
 * limits its own send endpoint — it exists so a user who mashes "resend" does
 * not get four codes in flight and then type the one that is no longer newest.
 */
export const RESEND_COOLDOWN_SECONDS = 60;

/**
 * Reduces whatever landed in the code field to the digits it contains.
 *
 * People paste "515 627" out of the mail body, and a paste out of a rendered
 * HTML mail carries zero-width characters (U+200B, U+FEFF) around the digits.
 * Neither is a typo worth an error message: keep the digits, drop the rest,
 * and cap the result at six so a doubled paste cannot 422.
 */
export function normaliseCode(raw: string): string {
  return raw.replace(/\D+/g, "").slice(0, CODE_LENGTH);
}

/** True once the field holds a code the backend will actually look at. */
export function isCompleteCode(code: string): boolean {
  return code.length === CODE_LENGTH && /^\d+$/.test(code);
}

/**
 * Seconds still to wait before another code may be requested.
 *
 * `lastSentAtMs` is null before the first send. Clamped at both ends: a clock
 * that resyncs backwards mid-flow must not lock the button for hours, and an
 * old timestamp must not produce a negative countdown. Rounded up, so the
 * label never reads "0s" while the button is still disabled.
 */
export function resendSecondsLeft(
  lastSentAtMs: number | null,
  nowMs: number,
): number {
  if (lastSentAtMs === null) return 0;
  const elapsedMs = nowMs - lastSentAtMs;
  if (elapsedMs < 0) return 0;
  const leftMs = RESEND_COOLDOWN_SECONDS * 1000 - elapsedMs;
  return leftMs <= 0 ? 0 : Math.ceil(leftMs / 1000);
}

/** True when the resend button should be live. */
export function canResend(lastSentAtMs: number | null, nowMs: number): boolean {
  return resendSecondsLeft(lastSentAtMs, nowMs) === 0;
}

/**
 * The HTTP status behind a rejected request, or 0 when the request never got
 * an answer (offline, DNS, CORS). 0 falls through to the generic copy in both
 * mappers below, which is the truth: we do not know what went wrong.
 */
export function statusOf(error: unknown): number {
  return error instanceof ApiError ? error.status : 0;
}

/**
 * Maps a failed `POST /auth/session` to user-facing copy.
 *
 * The 401 wording deliberately does not say whether the code was wrong or
 * expired. The backend cannot tell us apart either — WorkOS answers the same
 * for both — and distinguishing them would leak which codes existed while
 * telling the user nothing they would act on differently.
 */
export function signInErrorMessage(status: number): string {
  if (status === 401) return "That code is wrong or expired.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 503) {
    // `build_workos_client` returned None — the deployment has no WorkOS keys.
    // Blaming the code here sends the user round the send/type loop forever.
    return "Email sign-in isn't available right now. Try again later.";
  }
  return "Could not sign you in. Try again in a moment.";
}

/**
 * Maps a failed `POST /auth/code` to user-facing copy.
 *
 * Never reports whether the address has an account: the endpoint answers 202
 * either way precisely so the reply is not an existence oracle, and copy that
 * said "no account for that address" would hand back what the status code
 * withholds.
 */
export function sendCodeErrorMessage(status: number): string {
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 422) return "Please enter a valid email address.";
  if (status === 503) {
    return "Email sign-in isn't available right now. Try again later.";
  }
  return "Could not send the code. Try again in a moment.";
}
