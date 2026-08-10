const DEFAULT_BASE_URL = "http://localhost:8000";

const BASE_URL = (
  typeof import.meta.env.VITE_API_BASE_URL === "string" &&
  import.meta.env.VITE_API_BASE_URL.length > 0
    ? import.meta.env.VITE_API_BASE_URL
    : DEFAULT_BASE_URL
).replace(/\/+$/, "");

/** Absolute API origin — exported for the landing page guide's copyable
 *  snippets, so they always target the same host `apiFetch` uses. */
export const API_BASE_URL = BASE_URL;

export class ApiError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, body: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Auth providers register a getter so apiFetch can read the live token without
 * importing React. Kept as a module-scoped function pointer to avoid a
 * client → context circular import.
 */
type TokenGetter = () => string | null;
let tokenGetter: TokenGetter = () => null;

export function setAccessTokenGetter(getter: TokenGetter): void {
  tokenGetter = getter;
}

/** Event name dispatched on window when a 401 hits with a token attached. */
export const UNAUTHORIZED_EVENT = "agentpit:unauthorized";

/**
 * `RequestInit` plus an opt-out from the UNAUTHORIZED_EVENT dispatch below.
 *
 * Default (unset/false) keeps today's behaviour for every existing caller: a
 * 401 with a token attached means the session died, so we log out. Only a
 * caller re-authenticating with the account's OWN factor (a password re-auth
 * prompt, not a bearer-token check) should set this — there a 401 means "you
 * typed it wrong," the expected case, not "your session died."
 */
export type ApiFetchInit = RequestInit & { skipAuthEvent?: boolean | undefined };

export async function apiFetch<T>(
  path: string,
  init?: ApiFetchInit,
): Promise<T> {
  const url = `${BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
  const token = tokenGetter();
  const baseHeaders: Record<string, string> = { Accept: "application/json" };
  if (init?.body && typeof init.body === "string") {
    baseHeaders["Content-Type"] = "application/json";
  }
  if (token) {
    baseHeaders.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...init,
    headers: {
      ...baseHeaders,
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    if (response.status === 401 && token && !init?.skipAuthEvent) {
      // Server rejected our token (expired, secret rotated, account deleted).
      // The provider listens for this and clears local auth state.
      //
      // A password re-auth endpoint (change-password, key export) also
      // answers 401 for "you typed the wrong password" — nothing to do with
      // the bearer token above, which is still perfectly valid. Those
      // callers pass skipAuthEvent so a mistyped password doesn't log the
      // user out from under the dialog they're re-authenticating in. Do not
      // remove this opt-out to "simplify" the check.
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(
      response.status,
      body,
      `Request failed: ${response.status} ${response.statusText}${
        body ? ` — ${body.slice(0, 200)}` : ""
      }`,
    );
  }

  return (await response.json()) as T;
}
