import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_BASE_URL,
  ApiError,
  apiFetch,
  setAccessTokenGetter,
  setTokenRefresher,
  UNAUTHORIZED_EVENT,
} from "./client";

/**
 * The refresh-and-retry path. The AuthKit access token lives 300 seconds
 * (measured against staging, 2026-08-11), so without this every signed-in user
 * would be thrown out every five minutes; and a retry loop that got it wrong
 * would either hammer the API or log everybody out. Neither shows up in a
 * component test, so it is asserted here against a stubbed `fetch`.
 */

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;
let dispatchEvent: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  dispatchEvent = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  // node-env vitest has no `window`; apiFetch dispatches the dead-session
  // event on it.
  vi.stubGlobal("window", { dispatchEvent });
  setAccessTokenGetter(() => "stale-token");
  setTokenRefresher(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessTokenGetter(() => null);
  setTokenRefresher(null);
});

function authHeaderOf(call: number): string | undefined {
  const init = fetchMock.mock.calls[call]?.[1] as RequestInit | undefined;
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

describe("apiFetch refresh-and-retry", () => {
  it("refreshes on a 401 and replays the request with the fresh token", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    const refresher = vi.fn().mockResolvedValue("fresh-token");
    setTokenRefresher(refresher);

    const result = await apiFetch<{ ok: boolean }>("/me");

    expect(result).toEqual({ ok: true });
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(authHeaderOf(0)).toBe("Bearer stale-token");
    expect(authHeaderOf(1)).toBe("Bearer fresh-token");
    // The session survived, so nothing may tell the provider to log out.
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("replays to the same url with the same method and body", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { ok: true }));
    setTokenRefresher(vi.fn().mockResolvedValue("fresh-token"));

    await apiFetch("/orders", {
      method: "POST",
      body: JSON.stringify({ size: 1 }),
    });

    expect(fetchMock.mock.calls[1]?.[0]).toBe(`${API_BASE_URL}/orders`);
    const replay = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(replay.method).toBe("POST");
    expect(replay.body).toBe(JSON.stringify({ size: 1 }));
  });

  it("retries exactly once — a second 401 gives up rather than looping", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(401, {}));
    const refresher = vi.fn().mockResolvedValue("fresh-token");
    setTokenRefresher(refresher);

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(refresher).toHaveBeenCalledTimes(1);
    // The refreshed token was rejected too: the session really is dead.
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect((dispatchEvent.mock.calls[0]?.[0] as Event).type).toBe(
      UNAUTHORIZED_EVENT,
    );
  });

  it("logs out when the refresh itself fails instead of retrying blind", async () => {
    fetchMock.mockResolvedValueOnce(json(401, {}));
    setTokenRefresher(vi.fn().mockResolvedValue(null));

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it("survives a refresher that throws", async () => {
    fetchMock.mockResolvedValueOnce(json(401, {}));
    setTokenRefresher(vi.fn().mockRejectedValue(new Error("network down")));

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it("never refreshes for a skipAuthEvent caller", async () => {
    // This is what stops `/auth/session` and `/auth/refresh` — both of which
    // answer 401 in normal use — from recursing through the refresher that is
    // implemented in terms of them.
    fetchMock.mockResolvedValueOnce(json(401, {}));
    const refresher = vi.fn();
    setTokenRefresher(refresher);

    await expect(
      apiFetch("/auth/session", { skipAuthEvent: true }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(refresher).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("never refreshes when there was no token to begin with", async () => {
    setAccessTokenGetter(() => null);
    fetchMock.mockResolvedValueOnce(json(401, {}));
    const refresher = vi.fn();
    setTokenRefresher(refresher);

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(refresher).not.toHaveBeenCalled();
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it("leaves non-401 failures exactly as they were", async () => {
    fetchMock.mockResolvedValueOnce(json(500, { detail: "boom" }));
    const refresher = vi.fn();
    setTokenRefresher(refresher);

    await expect(apiFetch("/me")).rejects.toMatchObject({ status: 500 });

    expect(refresher).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("behaves as it always did when no refresher is registered", async () => {
    // The bots and any page loaded before the provider mounts.
    fetchMock.mockResolvedValueOnce(json(401, {}));

    await expect(apiFetch("/me")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });
});
