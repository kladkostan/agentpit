/**
 * The WorkOS redirect flow, as pure functions.
 *
 * `ui/` vitest is node-env with no `@testing-library/react`, so
 * `AuthCallbackPage` cannot be render-tested. Every decision therefore lives
 * here — keep it that way.
 */

/**
 * NOT `<authkit-domain>/oauth2/authorize`.
 *
 * WorkOS advertises both. The `/oauth2/*` endpoints issue tokens whose `iss`
 * is the AuthKit domain; `AuthKitVerifier` on the API pins
 * `https://api.workos.com/user_management/<client_id>`, which is what this
 * flow returns. Taking the more standard-looking path would have every sign-in
 * rejected by the API while the tests, which mint their own tokens, stayed
 * green.
 */
const AUTHORIZE_URL = "https://api.workos.com/user_management/authorize";

/** Trim to null, so a variable set to whitespace means "off" like an unset one.
 *  Read as a value rather than by dynamic key: `import.meta.env` is a typed
 *  interface, and indexing it with a union widens to `any` under
 *  `noImplicitAny` or fails outright. */
function present(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** Public by design — both appear in the URL of every sign-in. Absence means
 *  the feature is off and the button must not render, the same rule
 *  `GOOGLE_CLIENT_ID` follows in `googleAuth.ts`. */
export const WORKOS_CLIENT_ID = present(import.meta.env.VITE_WORKOS_CLIENT_ID);
export const WORKOS_REDIRECT_URI = present(
  import.meta.env.VITE_WORKOS_REDIRECT_URI,
);

/** Where the state lives between leaving the tab and coming back to it. */
export const STATE_KEY = "agentpit.oauth_state";

export function buildAuthorizeUrl(params: {
  clientId: string;
  redirectUri: string;
  provider: string;
  state: string;
}): string {
  const url = new URL(AUTHORIZE_URL);
  url.searchParams.set("client_id", params.clientId);
  url.searchParams.set("redirect_uri", params.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("provider", params.provider);
  url.searchParams.set("state", params.state);
  return url.toString();
}

export type CallbackParams = { code: string; state: string } | { error: string };

export function readCallbackParams(search: string): CallbackParams {
  const params = new URLSearchParams(search);
  const error = params.get("error");
  if (error) return { error };
  const code = params.get("code");
  // No code and no error is not an empty sign-in — it is somebody who opened
  // this URL by hand, or a redirect that lost its query string.
  if (!code) return { error: "missing_code" };
  return { code, state: params.get("state") ?? "" };
}

/**
 * Does the state that came back match the one we stored?
 *
 * Empty never matches empty. Without that, a link crafted by somebody else —
 * arriving at a browser that has stored nothing — would compare "" with "" and
 * complete a sign-in in a victim's session.
 */
export function stateMatches(
  returned: string | null,
  stored: string | null,
): boolean {
  if (!returned || !stored) return false;
  return returned === stored;
}

/** A fresh state value. `crypto` is injectable so this is testable. */
export function createState(source: Crypto = crypto): string {
  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
