const DEFAULT_BASE_URL = "http://localhost:8000";

function getBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL;
  return (typeof fromEnv === "string" && fromEnv.length > 0
    ? fromEnv
    : DEFAULT_BASE_URL
  ).replace(/\/+$/, "");
}

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

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${getBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
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
