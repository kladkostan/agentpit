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
import {
  CODE_LENGTH,
  canResend,
  isCompleteCode,
  normaliseCode,
  resendSecondsLeft,
  sendCodeErrorMessage,
  signInErrorMessage,
  statusOf,
} from "@/components/auth/codeFlow";

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

/** Which of the two mailed-code steps the dialog is showing. */
type Step = "email" | "code";

export function AuthDialog() {
  const {
    dialogOpen,
    dialogMode,
    closeDialog,
    setDialogMode,
    login,
    register,
    sendCode,
    signInWithCode,
    signInWithGoogle,
  } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<Step>("email");
  // The password form is still here on purpose: `/register` and `/login` are
  // untouched by this change, so a regression in the mailed-code path must not
  // lock anybody out. It goes when those endpoints go.
  const [usePassword, setUsePassword] = useState(false);
  const [lastSentAt, setLastSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Reset everything whenever the dialog re-opens.
  useEffect(() => {
    if (dialogOpen) {
      setEmail("");
      setPassword("");
      setCode("");
      setStep("email");
      setUsePassword(false);
      setLastSentAt(null);
      setError(null);
      setSubmitting(false);
    }
  }, [dialogOpen]);

  // Switching between Log in and Create account clears the password form. Not
  // folded into the effect above: toggling the mode must not throw the user
  // back out of the password form they just chose.
  useEffect(() => {
    setPassword("");
    setError(null);
  }, [dialogMode]);

  // Drives the resend countdown. Only ticks on the code step, so the rest of
  // the app never re-renders on a timer it cannot see.
  useEffect(() => {
    if (step !== "code") return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [step]);

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

  // Shared by the first send and every resend. Only advances to the code step
  // when the send actually succeeded — otherwise the user is asked for a code
  // that was never mailed.
  const requestCode = async (address: string) => {
    setSubmitting(true);
    try {
      await sendCode(address);
      setLastSentAt(Date.now());
      setCode("");
      setStep("code");
    } catch (err) {
      setError(sendCodeErrorMessage(statusOf(err)));
    } finally {
      setSubmitting(false);
    }
  };

  const onSendCode = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (!EMAIL_RE.test(email)) {
      setError("Please enter a valid email address.");
      return;
    }
    await requestCode(email);
  };

  const onVerifyCode = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (!isCompleteCode(code)) {
      setError(`Enter the ${CODE_LENGTH}-digit code from the email.`);
      return;
    }
    setSubmitting(true);
    try {
      await signInWithCode(email, code);
    } catch (err) {
      setError(signInErrorMessage(statusOf(err)));
    } finally {
      setSubmitting(false);
    }
  };

  const onResend = async () => {
    setError(null);
    await requestCode(email);
  };

  const onSubmitPassword = async (e: FormEvent<HTMLFormElement>) => {
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
  const passwordTitle = isLogin ? "Log in" : "Create account";
  const switchPrompt = isLogin ? "New here?" : "Already have an account?";
  const switchAction = isLogin ? "Create an account" : "Log in";
  const switchTo = isLogin ? "signup" : "login";

  const title = usePassword
    ? passwordTitle
    : step === "email"
      ? "Sign in"
      : "Check your email";

  const secondsLeft = resendSecondsLeft(lastSentAt, now);
  const resendReady = canResend(lastSentAt, now) && !submitting;

  // The product's own label device — mono micro-caps, the same one the market
  // cards use for anything that labels data.
  const fieldLabelClass =
    "font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground";
  const linkClass =
    "font-medium text-blue-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60 dark:text-blue-400";

  const errorBlock = error && (
    <p
      role="alert"
      className="text-sm text-destructive"
      data-testid="auth-error"
    >
      {error}
    </p>
  );

  const emailField = (
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
  );

  const googleBlock = GOOGLE_CLIENT_ID && (
    <div className="space-y-4">
      {/* Below the fields, not above them: the emailed code is the primary
          path, and the divider reads as "or, instead of the above". */}
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
  );

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

        {usePassword ? (
          <form onSubmit={onSubmitPassword} className="space-y-4">
            {emailField}
            <div className="space-y-1.5">
              <Label htmlFor="auth-password" className={fieldLabelClass}>
                Password
              </Label>
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
            {errorBlock}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? `${passwordTitle}…` : passwordTitle}
            </Button>
            {googleBlock}
            <p className="pt-1 text-center text-sm text-muted-foreground">
              {switchPrompt}{" "}
              <button
                type="button"
                className={linkClass}
                onClick={() => setDialogMode(switchTo)}
                disabled={submitting}
              >
                {switchAction}
              </button>
            </p>
            <p className="text-center text-sm text-muted-foreground">
              <button
                type="button"
                className={linkClass}
                onClick={() => {
                  setUsePassword(false);
                  setError(null);
                }}
                disabled={submitting}
              >
                Email me a code instead
              </button>
            </p>
          </form>
        ) : step === "email" ? (
          <form onSubmit={onSendCode} className="space-y-4">
            <p className="text-sm text-muted-foreground">
              We&rsquo;ll email you a {CODE_LENGTH}-digit code. No password
              needed — if you don&rsquo;t have an account yet, this creates one.
            </p>
            {emailField}
            {errorBlock}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Sending…" : "Email me a code"}
            </Button>
            {googleBlock}
            <p className="pt-1 text-center text-sm text-muted-foreground">
              <button
                type="button"
                className={linkClass}
                onClick={() => {
                  setUsePassword(true);
                  setError(null);
                }}
                disabled={submitting}
              >
                Use a password instead
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={onVerifyCode} className="space-y-4">
            <p className="text-sm text-muted-foreground">
              We sent a {CODE_LENGTH}-digit code to{" "}
              <span className="font-medium text-foreground">{email}</span>.
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="auth-code" className={fieldLabelClass}>
                Code
              </Label>
              <Input
                id="auth-code"
                // one-time-code lets the OS offer the code straight from the
                // mail; inputMode gets the numeric keypad on a phone.
                autoComplete="one-time-code"
                inputMode="numeric"
                autoFocus
                required
                maxLength={CODE_LENGTH}
                className="font-mono text-lg tracking-[0.4em]"
                value={code}
                // Normalised on the way in, not on submit: a paste of
                // "515 627" should look right in the field immediately.
                onChange={(e) => setCode(normaliseCode(e.target.value))}
                disabled={submitting}
              />
            </div>
            {errorBlock}
            <Button
              type="submit"
              className="w-full"
              disabled={submitting || !isCompleteCode(code)}
            >
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
            <p className="pt-1 text-center text-sm text-muted-foreground">
              {resendReady ? (
                <button
                  type="button"
                  className={linkClass}
                  onClick={() => void onResend()}
                >
                  Send a new code
                </button>
              ) : (
                <span>Send a new code in {secondsLeft}s</span>
              )}
            </p>
            <p className="text-center text-sm text-muted-foreground">
              <button
                type="button"
                className={linkClass}
                onClick={() => {
                  setStep("email");
                  setError(null);
                }}
                disabled={submitting}
              >
                Use a different email
              </button>
            </p>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
