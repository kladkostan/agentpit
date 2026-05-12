import { useEffect, useState, type FormEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/auth/useAuth";
import { ApiError } from "@/api/client";

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
  const title = isLogin ? "Log in" : "Sign up";
  const description = isLogin
    ? "Welcome back. Sign in to keep trading."
    : "Create an account — we'll mint your wallet and starter balance for you.";
  const submitLabel = isLogin ? "Log in" : "Sign up";
  const switchLabel = isLogin
    ? "Don't have an account? Sign up"
    : "Already have an account? Log in";
  const switchTo = isLogin ? "signup" : "login";

  return (
    <Dialog
      open={dialogOpen}
      onOpenChange={(next) => {
        if (!next) closeDialog();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="auth-email">Email</Label>
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
          <div className="space-y-2">
            <Label htmlFor="auth-password">Password</Label>
            <Input
              id="auth-password"
              type="password"
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
          <div className="text-center text-sm text-muted-foreground">
            <button
              type="button"
              className="underline-offset-4 hover:underline"
              onClick={() => setDialogMode(switchTo)}
              disabled={submitting}
            >
              {switchLabel}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
