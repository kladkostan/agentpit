import { useEffect, useState, type FormEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/auth/useAuth";
import { ApiError } from "@/api/client";
import { GOOGLE_CLIENT_ID } from "@/lib/googleAuth";
import { GoogleSignInButton } from "@/components/auth/GoogleSignInButton";

const EMAIL_RE = /.+@.+\..+/;
const MIN_PASSWORD_LENGTH = 8;

function extractDetail(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.body) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
      if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
        // FastAPI 422: array of {msg, loc, ...}; surface the first message.
        const first = parsed.detail[0] as { msg?: unknown };
        if (typeof first.msg === "string") return first.msg;
      }
    } catch {
      /* fall through to error.message */
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong";
}

export function AuthDialog() {
  const {
    dialogOpen,
    dialogMode,
    closeDialog,
    setDialogMode,
    login,
    register,
    signInWithGoogle,
  } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Reset form whenever the dialog re-opens or the mode changes.
  useEffect(() => {
    if (dialogOpen) {
      setEmail("");
      setPassword("");
      setError(null);
      setSubmitting(false);
    }
  }, [dialogOpen, dialogMode]);

  const onGoogleCredential = async (credential: string) => {
    setError(null);
    setSubmitting(true);
    try {
      await signInWithGoogle(credential);
    } catch (err) {
      setError(extractDetail(err));
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    if (!EMAIL_RE.test(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      if (dialogMode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
    } catch (err) {
      setError(extractDetail(err));
    } finally {
      setSubmitting(false);
    }
  };

  const isLogin = dialogMode === "login";
  const title = isLogin ? "Log in" : "Create account";
  const submitLabel = title;
  const switchPrompt = isLogin ? "New here?" : "Already have an account?";
  const switchAction = isLogin ? "Create an account" : "Log in";
  const switchTo = isLogin ? "signup" : "login";

  // The product's own label device — mono micro-caps, the same one the market
  // cards use for anything that labels data.
  const fieldLabelClass =
    "font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground";

  return (
    <Dialog
      open={dialogOpen}
      onOpenChange={(next) => {
        if (!next) closeDialog();
      }}
    >
      {/* A dialog that touches both edges of a phone screen reads as a page
          that failed to load, not as a panel. */}
      <DialogContent
        className="w-[calc(100%-2rem)] sm:max-w-md"
        aria-describedby={undefined}
      >
        <DialogHeader className="pr-6 text-left">
          <DialogTitle className="text-xl font-semibold tracking-tight">
            {title}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="auth-email" className={fieldLabelClass}>
              Email
            </Label>
            <Input
              id="auth-email"
              type="email"
              autoComplete="email"
              autoFocus
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <Label htmlFor="auth-password" className={fieldLabelClass}>
                Password
              </Label>
              {/* Say the rule before they break it, not after. */}
              {!isLogin && (
                // Full muted, not a faded variant: at 10px this is the only
                // place the rule appears before somebody trips over it, and a
                // dimmed version of it fails contrast for the people who most
                // need to read it.
                <span id="auth-password-hint" className={fieldLabelClass}>
                  {MIN_PASSWORD_LENGTH}+ characters
                </span>
              )}
            </div>
            <Input
              id="auth-password"
              type="password"
              aria-describedby={isLogin ? undefined : "auth-password-hint"}
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
          </div>
          {error && (
            <p
              role="alert"
              className="text-sm text-destructive"
              data-testid="auth-error"
            >
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? `${submitLabel}…` : submitLabel}
          </Button>
          {/* Below the fields, not above them: email and password are the
              primary path, and the divider reads as "or, instead of the
              above". Both tabs get it — somebody who signed up with Google
              needs the same button to sign back in. */}
          {GOOGLE_CLIENT_ID && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="h-px flex-1 bg-border" />
                <span className={fieldLabelClass}>or</span>
                <span className="h-px flex-1 bg-border" />
              </div>
              <GoogleSignInButton
                onCredential={(credential) => void onGoogleCredential(credential)}
                onError={setError}
              />
            </div>
          )}
          <p className="pt-1 text-center text-sm text-muted-foreground">
            {switchPrompt}{" "}
            <button
              type="button"
              className="font-medium text-blue-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60 dark:text-blue-400"
              onClick={() => setDialogMode(switchTo)}
              disabled={submitting}
            >
              {switchAction}
            </button>
          </p>
        </form>
      </DialogContent>
    </Dialog>
  );
}
