/**
 * Google Identity Services glue.
 *
 * The client id is public by design — it sits in the page of every site that
 * uses Google sign-in — but its absence is meaningful: no id means the feature
 * is off, and the button must not render at all.
 */

const GIS_SRC = "https://accounts.google.com/gsi/client";
const GIS_SCRIPT_ID = "google-identity-services";

export function readGoogleClientId(env: {
  VITE_GOOGLE_CLIENT_ID?: string;
}): string | null {
  const raw = env.VITE_GOOGLE_CLIENT_ID;
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** Baked in at build time by Vite. Null when the build had no client id. */
export const GOOGLE_CLIENT_ID = readGoogleClientId(import.meta.env);

let loading: Promise<void> | null = null;
// Set once a load attempt has failed. A stale script tag left over from that
// failed attempt would otherwise satisfy the "already present" check below
// forever, so a retry has to skip it and inject a fresh one.
let previousAttemptFailed = false;

/** Load Google's script once per tab. `doc` is injectable so the loader can be
 *  tested without a DOM. */
export function loadGoogleIdentity(doc: Document = document): Promise<void> {
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    if (!previousAttemptFailed && doc.getElementById(GIS_SCRIPT_ID)) {
      resolve();
      return;
    }
    const script = doc.createElement("script");
    script.id = GIS_SCRIPT_ID;
    script.src = GIS_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      previousAttemptFailed = false;
      resolve();
    };
    script.onerror = () => {
      // Forget the failure: a cached rejected promise would make one blocked
      // request permanent for the tab, so a user on a flaky connection could
      // never try again without a reload.
      loading = null;
      previousAttemptFailed = true;
      reject(new Error("Google sign-in failed to load"));
    };
    doc.head.appendChild(script);
  });
  return loading;
}

type CredentialResponse = { credential?: string };

type GoogleIdentityApi = {
  accounts: {
    id: {
      initialize(config: {
        client_id: string;
        callback: (response: CredentialResponse) => void;
      }): void;
      renderButton(
        parent: HTMLElement,
        options: {
          type?: "standard" | "icon";
          theme?: "outline" | "filled_blue" | "filled_black";
          size?: "small" | "medium" | "large";
          text?: "signin_with" | "signup_with" | "continue_with";
          shape?: "rectangular" | "pill";
          width?: number;
        },
      ): void;
    };
  };
};

declare global {
  interface Window {
    google?: GoogleIdentityApi;
  }
}

export type { CredentialResponse, GoogleIdentityApi };
