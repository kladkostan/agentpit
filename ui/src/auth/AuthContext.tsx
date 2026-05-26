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
  loginRequest,
  meRequest,
  registerRequest,
  type UserPublic,
} from "@/api/auth";
import { setAccessTokenGetter, UNAUTHORIZED_EVENT } from "@/api/client";
import { AuthContext, type AuthValue, type DialogMode } from "./context";

const TOKEN_KEY = "agentpit.access_token";

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode etc. — token only lives in memory this session */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [accessToken, setAccessToken] = useState<string | null>(() =>
    readStoredToken(),
  );
  const [user, setUser] = useState<UserPublic | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(() =>
    readStoredToken() !== null,
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("login");

  // Keep the api client in sync with the live token without a circular import.
  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;
  useEffect(() => {
    setAccessTokenGetter(() => tokenRef.current);
  }, []);

  const persistToken = useCallback((token: string | null) => {
    writeStoredToken(token);
    tokenRef.current = token;
    setAccessToken(token);
  }, []);

  const logout = useCallback(() => {
    persistToken(null);
    setUser(null);
    queryClient.clear();
  }, [persistToken, queryClient]);

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

  // On mount, if we have a token, hydrate the user via /me.
  useEffect(() => {
    let cancelled = false;
    if (!accessToken) {
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
    // through login/register which set the user themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openLogin = useCallback(() => {
    setDialogMode("login");
    setDialogOpen(true);
  }, []);

  const openSignup = useCallback(() => {
    setDialogMode("signup");
    setDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => setDialogOpen(false), []);

  const login = useCallback<AuthValue["login"]>(
    async (email, password) => {
      const resp = await loginRequest(email, password);
      persistToken(resp.access_token);
      setUser(resp.user);
      setDialogOpen(false);
    },
    [persistToken],
  );

  const register = useCallback<AuthValue["register"]>(
    async (email, password) => {
      const resp = await registerRequest(email, password);
      persistToken(resp.access_token);
      setUser(resp.user);
      setDialogOpen(false);
    },
    [persistToken],
  );

  const value = useMemo<AuthValue>(
    () => ({
      user,
      setUser,
      accessToken,
      isLoading,
      dialogOpen,
      dialogMode,
      openLogin,
      openSignup,
      closeDialog,
      setDialogMode,
      login,
      register,
      logout,
    }),
    [
      user,
      setUser,
      accessToken,
      isLoading,
      dialogOpen,
      dialogMode,
      openLogin,
      openSignup,
      closeDialog,
      login,
      register,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
