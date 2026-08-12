import { describe, expect, it } from "vitest";
import {
  buildAuthorizeUrl,
  createState,
  present,
  readCallbackParams,
  stateMatches,
} from "./workosAuth";

describe("present", () => {
  // Mirrors `readGoogleClientId` in `googleAuth.ts` — same rule, same cases,
  // because this is the function that decides whether `WORKOS_CLIENT_ID` /
  // `WORKOS_REDIRECT_URI` count as set, which gates whether the Google button
  // renders at all in `AuthDialog`.
  it("returns the value when set", () => {
    expect(present("client_1")).toBe("client_1");
  });

  it("treats a non-string as off", () => {
    expect(present(undefined)).toBeNull();
    expect(present(null)).toBeNull();
  });

  it("treats an empty or blank string as off", () => {
    // A build arg that resolved to nothing must switch the feature off, not
    // send WorkOS a `client_id` of spaces.
    expect(present("")).toBeNull();
    expect(present("   ")).toBeNull();
  });

  it("trims surrounding whitespace", () => {
    expect(present(" client_1 \n")).toBe("client_1");
  });
});

describe("buildAuthorizeUrl", () => {
  it("targets the user_management authorize endpoint, not oauth2", () => {
    // The `/oauth2/authorize` endpoint on the AuthKit domain issues tokens
    // with a different `iss` than AuthKitVerifier pins, so every sign-in
    // through it would be rejected by the API.
    const url = buildAuthorizeUrl({
      clientId: "client_1",
      redirectUri: "http://localhost:5173/auth/callback",
      provider: "GoogleOAuth",
      state: "st",
    });
    expect(url).toContain("https://api.workos.com/user_management/authorize");
    expect(url).not.toContain("/oauth2/");
  });

  it("carries the client id, redirect, provider, state and response type", () => {
    const url = new URL(
      buildAuthorizeUrl({
        clientId: "client_1",
        redirectUri: "http://localhost:5173/auth/callback",
        provider: "GoogleOAuth",
        state: "st",
      }),
    );
    expect(url.searchParams.get("client_id")).toBe("client_1");
    expect(url.searchParams.get("redirect_uri")).toBe(
      "http://localhost:5173/auth/callback",
    );
    expect(url.searchParams.get("provider")).toBe("GoogleOAuth");
    expect(url.searchParams.get("state")).toBe("st");
    expect(url.searchParams.get("response_type")).toBe("code");
  });
});

describe("readCallbackParams", () => {
  it("reads a code and state", () => {
    expect(readCallbackParams("?code=abc&state=st")).toEqual({
      code: "abc",
      state: "st",
    });
  });

  it("reports the provider's error instead of a code", () => {
    expect(readCallbackParams("?error=access_denied")).toEqual({
      error: "access_denied",
    });
  });

  it("treats a missing code as an error rather than an empty sign-in", () => {
    expect(readCallbackParams("")).toEqual({ error: "missing_code" });
  });
});

describe("stateMatches", () => {
  it("is true only for an exact match", () => {
    expect(stateMatches("st", "st")).toBe(true);
    expect(stateMatches("st", "other")).toBe(false);
  });

  it("is false when either side is missing", () => {
    // A link crafted by somebody else arrives with no stored state. Accepting
    // that completes a sign-in in a victim's browser.
    expect(stateMatches("st", null)).toBe(false);
    expect(stateMatches(null, "st")).toBe(false);
    expect(stateMatches(null, null)).toBe(false);
  });

  it("is false for the empty string on both sides", () => {
    expect(stateMatches("", "")).toBe(false);
  });
});

describe("createState", () => {
  it("returns 16 bytes as lowercase hex, from whatever source it's given", () => {
    // Deterministic in shape only — the value itself must not be asserted,
    // or the test would just be re-deriving the fill pattern below.
    const fakeCrypto = {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.forEach((_, i) => {
          bytes[i] = i;
        });
        return bytes;
      },
    } as unknown as Crypto;

    const state = createState(fakeCrypto);
    expect(state).toHaveLength(32);
    expect(state).toMatch(/^[0-9a-f]{32}$/);
  });

  it("asks the injected source for randomness rather than always using the global", () => {
    let calls = 0;
    const fakeCrypto = {
      getRandomValues: (bytes: Uint8Array) => {
        calls += 1;
        return bytes;
      },
    } as unknown as Crypto;

    createState(fakeCrypto);
    expect(calls).toBe(1);
  });
});
