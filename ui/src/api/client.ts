const DEFAULT_BASE_URL = "http://localhost:8000";

const BASE_URL = (
  typeof import.meta.env.VITE_API_BASE_URL === "string" &&
  import.meta.env.VITE_API_BASE_URL.length > 0
    ? import.meta.env.VITE_API_BASE_URL
    : DEFAULT_BASE_URL
).replace(/\/+$/, "");

/** Absolute API origin — exported for the /get-started guide's copyable
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

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
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
    if (response.status === 401 && token) {
      // Server rejected our token (expired, secret rotated, account deleted).
      // The provider listens for this and clears local auth state.
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
