import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { statusOf } from "@/components/auth/codeFlow";
import {
  callbackErrorMessage,
  readCallbackParams,
  stateMatches,
  STATE_KEY,
} from "@/lib/workosAuth";

/**
 * Where a WorkOS provider redirect lands.
 *
 * This page exists rather than the redirect pointing at an API route because
 * the exchange needs `client_secret`, which is our WorkOS API key. The browser
 * may carry the authorization code; it may never carry the secret. So the code
 * arrives here and goes to the backend by POST.
 */
export function AuthCallbackPage() {
  const navigate = useNavigate();
  const { signInWithCallbackCode } = useAuth();
  const [error, setError] = useState<string | null>(null);
  // WorkOS burns an authorization code on first use, and React 18 StrictMode
  // mounts effects twice in development. Without this guard the second post
  // fails on an already-spent code and paints an error over a sign-in that
  // actually succeeded.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const params = readCallbackParams(window.location.search);
    const stored = sessionStorage.getItem(STATE_KEY);
    // Read once and cleared immediately, whatever happens next: a state left
    // behind is a state that can be replayed.
    sessionStorage.removeItem(STATE_KEY);

    if ("error" in params) {
      setError("Sign-in was cancelled or did not complete.");
      return;
    }
    if (!stateMatches(params.state, stored)) {
      // Either this tab never started a sign-in, or the value came back
      // altered. Both mean somebody else's link opened in this browser.
      setError("That sign-in link didn't come from this browser.");
      return;
    }

    void (async () => {
      try {
        await signInWithCallbackCode(params.code);
        // `replace`, so Back does not return to a URL holding a spent code.
        navigate("/", { replace: true });
      } catch (err) {
        setError(callbackErrorMessage(statusOf(err)));
      }
    })();
  }, [navigate, signInWithCallbackCode]);

  return (
    <div className="mx-auto max-w-md py-16 text-center">
      {error ? (
        <div className="space-y-4">
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          <Link to="/" className="text-sm text-blue-600 underline-offset-4 hover:underline dark:text-blue-400">
            Back to agentpit
          </Link>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Signing you in…</p>
      )}
    </div>
  );
}
