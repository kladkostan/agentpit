/**
 * Maps a failed `POST /me/private-key` response to user-facing copy.
 *
 * Status alone is ambiguous: the backend picks the re-auth factor by what the
 * account HAS, not by what the dialog assumes, so a 401 means different
 * things for a password account and a Google account, and a 400 means either
 * the cooldown or a client whose idea of `has_password` has gone stale (e.g.
 * Google was linked in another tab and `AuthContext` only hydrates `/me` on
 * mount). Getting this wrong is exactly how the dialog used to tell a Google
 * user their non-existent password was incorrect.
 *
 * `body` is the raw `ApiError.body` text — the JSON the backend sent, e.g.
 * `{"detail":"too many attempts — wait a moment"}`. Checked by substring
 * rather than parsed, so a body that fails to parse still degrades to the
 * generic wrong-factor copy instead of throwing.
 */
export function exportErrorMessage(
  status: number,
  hasPassword: boolean,
  body: string,
): string {
  if (status === 401) {
    // A 401 only ever comes back for the factor the account actually has
    // (see the module doc), so `hasPassword` — unlike for a 400 — is not
    // stale here: whichever branch the backend took to reach a 401 is the
    // same branch this dialog is showing.
    return hasPassword
      ? "Incorrect password."
      : "That Google account isn't the one signed in to agentpit.";
  }
  if (status === 400) {
    return body.includes("too many attempts")
      ? "Too many attempts. Wait a moment and try again."
      : "This account's sign-in method changed. Refresh the page and try again.";
  }
  if (status === 503) {
    return "Google sign-in isn't available right now, so this account can't export its key. Try again later.";
  }
  return "Failed to export private key.";
}
