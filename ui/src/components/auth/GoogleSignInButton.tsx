import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID, loadGoogleIdentity } from "@/lib/googleAuth";

interface GoogleSignInButtonProps {
  onCredential: (credential: string) => void;
  onError: (message: string) => void;
}

/** Google's four-colour G, from their branding assets. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-[18px] shrink-0" aria-hidden>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.46 14.97.5 12 .5A11 11 0 0 0 2.18 7.05l3.66 2.84c.87-2.6 3.3-4.14 6.16-4.14z"
      />
    </svg>
  );
}

/**
 * "Continue with Google", in this product's button style rather than Google's.
 *
 * Google's script renders its button into a cross-origin iframe: none of it can
 * be styled, and every variant of it carries the white logo tile, which reads
 * as a foreign object next to our own buttons. The ID-token flow has no "start
 * it yourself" call either — only One Tap, which the browser is free to
 * suppress. So the real button is still Google's, rendered at exactly this
 * element's size and laid over it at zero opacity: the click, the popup and the
 * credential are all Google's, and the only thing that is ours is the surface
 * underneath.
 *
 * Renders nothing when the build has no client id.
 */
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
    let observer: ResizeObserver | undefined;

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

        // The invisible button has to cover ours exactly, or part of the
        // surface a person is aiming at does nothing. GIS takes a fixed pixel
        // width (200–400) and nothing responsive, so it is measured from the
        // box and re-applied whenever that box changes size.
        const host = hostRef.current;
        const box = host.parentElement;

        const draw = () => {
          const available = box ? box.clientWidth : host.offsetWidth;
          window.google?.accounts.id.renderButton(host, {
            type: "standard",
            theme: "outline",
            size: "large",
            text: "continue_with",
            shape: "rectangular",
            locale: "en",
            width: Math.min(400, Math.max(200, Math.round(available))),
          });
        };

        draw();
        if (box && typeof ResizeObserver !== "undefined") {
          observer = new ResizeObserver(() => {
            if (!cancelled) draw();
          });
          observer.observe(box);
        }
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
      observer?.disconnect();
    };
  }, []);

  if (!GOOGLE_CLIENT_ID) return null;

  return (
    // `focus-within` and `hover` land on this box — the element the person is
    // actually pointing at is Google's iframe on top, so the surface below has
    // to take its states from the box they share.
    <div className="group relative h-10 w-full">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2.5 rounded-md border border-input bg-background text-sm font-medium text-foreground transition-colors group-hover:bg-accent group-focus-within:ring-2 group-focus-within:ring-ring group-focus-within:ring-offset-2 group-focus-within:ring-offset-background"
      >
        <GoogleMark />
        Continue with Google
      </div>
      <div
        ref={hostRef}
        className="absolute inset-0 overflow-hidden opacity-0 [&_iframe]:!m-0"
      />
    </div>
  );
}
