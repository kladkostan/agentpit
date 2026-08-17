/**
 * Maps a failed `POST /me/private-key` response to user-facing copy.
 *
 * `hasPassword` is gone with the factor it selected: every account
 * re-authenticates with a mailed code, so a status now means one thing.
 *
 * `body` is the raw `ApiError.body` text — the JSON the backend sent, e.g.
 * `{"detail":"too many attempts — wait a moment"}`. Checked by substring
 * rather than parsed, so a body that fails to parse still degrades to generic
 * copy instead of throwing.
 */
export function exportErrorMessage(status: number, body: string): string {
  // Wrong and expired are one failure, and the backend cannot tell them apart
  // either — WorkOS answers the same for both.
  if (status === 401) return "That code is wrong or expired.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 400) {
    return body.includes("too many attempts")
      ? "Too many attempts. Wait a moment and try again."
      : "Sign in again, then retry the export.";
  }
  if (status === 503) {
    return "Key export isn't available right now. Try again later.";
  }
  return "Failed to export private key.";
}

/**
 * Maps a failed `POST /me/private-key/code` — asking for the code — to copy.
 *
 * Distinct from `exportErrorMessage` because of 401. There, 401 means the six
 * digits were wrong. Here nothing has been typed yet: the request carries only
 * the bearer token, so a 401 is the session itself being refused. `apiFetch`
 * sends this one WITHOUT `skipAuthEvent`, so that 401 also dispatches
 * UNAUTHORIZED_EVENT and the user is logged out underneath the dialog — telling
 * them their code was wrong leaves them retrying a dialog that is about to
 * disappear.
 *
 * No `body` parameter: `send_key_export_code` raises only FeatureDisabledError
 * and UserNotFoundError, so unlike the export itself there is no 400 whose
 * meaning has to be read out of the response text.
 */
export function sendExportCodeErrorMessage(status: number): string {
  if (status === 401) return "Your session expired. Sign in again to export.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 503) {
    return "Key export isn't available right now. Try again later.";
  }
  return "Could not send the code. Try again in a moment.";
}
