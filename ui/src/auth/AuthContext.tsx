import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  completeCallbackRequest,
  googleSignInRequest,
  meRequest,
  refreshSessionRequest,
  sendCodeRequest,
  signInWithCodeRequest,
  type UserPublic,
} from "@/api/auth";
import {
  setAccessTokenGetter,
  setTokenRefresher,
  UNAUTHORIZED_EVENT,
} from "@/api/client";
import {
  refreshFailureEndsSession,
  statusOf,
} from "@/components/auth/codeFlow";
import { hydratesFromStoredToken } from "@/lib/workosAuth";
import { AuthContext, type AuthValue } from "./context";
import { showWelcomeToast } from "./welcomeToast";

const TOKEN_KEY = "agentpit.access_token";
// The AuthKit access token lives 300 seconds (measured against staging,
// 2026-08-11), so the refresh token — which does not rotate — is what actually
// keeps a session alive across a reload.
const REFRESH_KEY = "agentpit.refresh_token";

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* private mode etc. — value only lives in memory this session */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [accessToken, setAccessToken] = useState<string | null>(() =>
    readStored(TOKEN_KEY),
  );
  const [user, setUser] = useState<UserPublic | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(() =>
    readStored(TOKEN_KEY) !== null,
  );
  const [dialogOpen, setDialogOpen] = useState(false);

  // Keep the api client in sync with the live token without a circular import.
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;
  useEffect(() => {
    setAccessTokenGetter(() => tokenRef.current);
  }, []);

  const persistToken = useCallback((token: string | null) => {
    writeStored(TOKEN_KEY, token);
    tokenRef.current = token;
    setAccessToken(token);
  }, []);

  // Nothing renders from the refresh token, so it stays a ref: putting it in
  // state would re-render the whole tree every time a background refresh lands.
  const refreshTokenRef = useRef<string | null>(readStored(REFRESH_KEY));

  const persistRefreshToken = useCallback((token: string | null) => {
    writeStored(REFRESH_KEY, token);
    refreshTokenRef.current = token;
  }, []);

  const logout = useCallback(() => {
    persistToken(null);
    persistRefreshToken(null);
    setUser(null);
    queryClient.clear();
  }, [persistToken, persistRefreshToken, queryClient]);

  // A 401 on any request is repaired here rather than ending the session: the
  // access token expires after 300 seconds, so without this every signed-in
  // user would be thrown out every five minutes. `client.ts` calls this at
  // most once per request and replays the original with whatever comes back.
  const refreshInFlight = useRef<Promise<string | null> | null>(null);

  const refreshAccessToken = useCallback(async (): Promise<string | null> => {
    const stored = refreshTokenRef.current;
    if (!stored) return null;
    // A page usually has several requests in flight, and they all 401 at the
    // same moment. Share one refresh between them instead of sending five.
    const existing = refreshInFlight.current;
    if (existing) return existing;
    const attempt = (async () => {
      try {
        const resp = await refreshSessionRequest(stored);
        persistToken(resp.access_token);
        persistRefreshToken(resp.refresh_token);
        setUser(resp.user);
        return resp.access_token;
      } catch (err) {
        // Only a rejection of the credential itself ends the session. An
        // outage must not: WorkOS does not rotate refresh tokens, so the copy
        // in storage is the only copy, and deleting it on a 503 sends
        // everybody who was signed in at that moment back to their inbox.
        if (refreshFailureEndsSession(statusOf(err))) {
          logout();
        }
        return null;
      } finally {
        refreshInFlight.current = null;
      }
    })();
    refreshInFlight.current = attempt;
    return attempt;
  }, [logout, persistRefreshToken, persistToken]);

  useEffect(() => {
    setTokenRefresher(refreshAccessToken);
    return () => setTokenRefresher(null);
  }, [refreshAccessToken]);

  // If a 401 fires after the initial bootstrap, drop local auth state so the
  // user sees the Log in / Sign up buttons again.
  useEffect(() => {
    const handler = () => {
      if (tokenRef.current) {
        logout();
      }
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  }, [logout]);

  // On mount, if we have a token, hydrate the user via /me — unless the app
  // was loaded straight onto the callback route, where doing so races the code
  // exchange and can end the session it just created. The reasoning is on
  // `hydratesFromStoredToken`; it lives there so it is covered, since this
  // component cannot be render-tested.
  useEffect(() => {
    let cancelled = false;
    if (!hydratesFromStoredToken(window.location.pathname, accessToken)) {
      // Loading has to end either way. Leaving it true for the callback page
      // to clear would strand the nav in a loading state whenever the exchange
      // fails; the cost of clearing it now is a brief logged-out nav over a
      // page that already reads "Signing you in…".
      setIsLoading(false);
      return;
    }
    (async () => {
      try {
        const me = await meRequest();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) {
          // /me failed — token is stale or server rejected it.
          persistToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // We only want this to run once on mount; subsequent token changes go
    // through signInWithCode, signInWithCallbackCode or refreshAccessToken,
    // all of which set the user themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Two names, one dialog. Signing in and signing up stopped being different
  // actions at the cutover — a mailed code creates the account if there isn't
  // one — but the callers still read differently at their call sites, so the
  // pair stays rather than every one of them switching to `openDialog`.
  const openLogin = useCallback(() => setDialogOpen(true), []);
  const openSignup = useCallback(() => setDialogOpen(true), []);

  const closeDialog = useCallback(() => setDialogOpen(false), []);

  const sendCode = useCallback<AuthValue["sendCode"]>(async (email) => {
    await sendCodeRequest(email);
  }, []);

  const signInWithCode = useCallback<AuthValue["signInWithCode"]>(
    async (email, code) => {
      const resp = await signInWithCodeRequest(email, code);
      persistToken(resp.access_token);
      persistRefreshToken(resp.refresh_token);
      setUser(resp.user);
      setDialogOpen(false);
    },
    [persistRefreshToken, persistToken],
  );

  const signInWithCallbackCode = useCallback<
    AuthValue["signInWithCallbackCode"]
  >(
    async (code) => {
      const resp = await completeCallbackRequest(code);
      persistToken(resp.access_token);
      persistRefreshToken(resp.refresh_token);
      setUser(resp.user);
      setDialogOpen(false);
    },
    [persistRefreshToken, persistToken],
  );

  const signInWithGoogle = useCallback<AuthValue["signInWithGoogle"]>(
    async (credential) => {
      const resp = await googleSignInRequest(credential);
      persistToken(resp.access_token);
      persistRefreshToken(resp.refresh_token);
      setUser(resp.user);
      setDialogOpen(false);
      // Only a brand-new account gets the greeting — a returning user has seen
      // it, and being told their wallet was just funded would be untrue.
      if (resp.created) showWelcomeToast();
    },
    [persistRefreshToken, persistToken],
  );

  const value = useMemo<AuthValue>(
    () => ({
      user,
      setUser,
      accessToken,
      isLoading,
      dialogOpen,
      openLogin,
      openSignup,
      closeDialog,
      sendCode,
      signInWithCode,
      signInWithGoogle,
      signInWithCallbackCode,
      logout,
    }),
    [
      user,
      setUser,
      accessToken,
      isLoading,
      dialogOpen,
      openLogin,
      openSignup,
      closeDialog,
      sendCode,
      signInWithCode,
      signInWithGoogle,
      signInWithCallbackCode,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
