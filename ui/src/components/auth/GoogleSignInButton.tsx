import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID, loadGoogleIdentity } from "@/lib/googleAuth";
import { useTheme } from "@/lib/theme";

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
  const { theme } = useTheme();
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
        // Google renders into an iframe we cannot style, so the one thing we
        // can match is its width — otherwise it sits visibly narrower than the
        // full-width submit button above it. GIS takes a fixed pixel width
        // (200–400) and nothing responsive, so the width has to be measured
        // and re-applied whenever the column changes size. Measure the parent,
        // not the host: the host's own width is a consequence of the button we
        // are about to draw into it, which would make this observe itself.
        const host = hostRef.current;
        const column = host.parentElement;

        const draw = () => {
          const available = column ? column.clientWidth : host.offsetWidth;
          window.google?.accounts.id.renderButton(host, {
            type: "standard",
            // The submit button above is `--primary`, which flips with the
            // theme: near-black on light, near-white on dark. Google's button
            // has to flip the other way or the two stack up as one weight and
            // neither reads as the alternative to the other.
            theme: theme === "dark" ? "filled_black" : "outline",
            size: "large",
            text: "continue_with",
            shape: "rectangular",
            // The rest of the product is English-only, so ask for English.
            // It arrives as `hl=en` on the iframe, but Google decides the
            // final wording — a viewer whose Google account is set to another
            // language gets that language, and there is no lever for it here.
            locale: "en",
            width: Math.min(400, Math.max(200, Math.round(available))),
          });
        };

        draw();
        if (column && typeof ResizeObserver !== "undefined") {
          // A phone rotated while the dialog is open would otherwise leave a
          // 400px button inside a 327px column, pushing the whole dialog off
          // the side of the screen.
          observer = new ResizeObserver(() => {
            if (!cancelled) draw();
          });
          observer.observe(column);
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
    // Redrawn when the theme flips: the button's light/dark variant is baked
    // into the iframe at render time, so it cannot follow a CSS class.
  }, [theme]);

  if (!GOOGLE_CLIENT_ID) return null;
  // `overflow-hidden` is the backstop: between a resize and the redraw there is
  // one frame where the old fixed-width button is still in place, and without
  // it that frame widens the dialog.
  return <div ref={hostRef} className="flex justify-center overflow-hidden" />;
}
