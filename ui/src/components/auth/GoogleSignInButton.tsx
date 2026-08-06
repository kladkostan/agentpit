import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID, loadGoogleIdentity } from "@/lib/googleAuth";

interface GoogleSignInButtonProps {
  onCredential: (credential: string) => void;
  onError: (message: string) => void;
}

/** Google's own button, rendered by their script into a host element.
 *  Renders nothing when the build has no client id. */
export function GoogleSignInButton({
  onCredential,
  onError,
}: GoogleSignInButtonProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  // GIS keeps the callback it was initialised with; the ref lets that fixed
  // callback reach the current handlers without re-initialising on every
  // render.
  const handlers = useRef({ onCredential, onError });
  handlers.current = { onCredential, onError };

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    // Narrowing an imported const doesn't survive into a nested closure, so
    // capture it locally once we know it's set.
    const clientId = GOOGLE_CLIENT_ID;
    let cancelled = false;

    loadGoogleIdentity()
      .then(() => {
        if (cancelled || !hostRef.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => {
            if (response.credential) {
              handlers.current.onCredential(response.credential);
            } else {
              handlers.current.onError("Google did not return a credential.");
            }
          },
        });
        window.google.accounts.id.renderButton(hostRef.current, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          width: 360,
        });
      })
      .catch(() => {
        if (!cancelled) {
          handlers.current.onError(
            "Google sign-in is unavailable right now. Use email and password.",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!GOOGLE_CLIENT_ID) return null;
  return <div ref={hostRef} className="flex justify-center" />;
}
