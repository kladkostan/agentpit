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
