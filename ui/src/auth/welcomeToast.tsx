import { toast } from "sonner";

/** First sign-up: a prominent, top-center welcome so new users immediately see
 *  their wallet is funded. Deferred a beat so it pops after the auth dialog
 *  closes rather than behind it. */
export function showWelcomeToast(): void {
  window.setTimeout(() => {
    toast.custom(
      () => (
        <div className="flex w-[min(92vw,460px)] items-start gap-3 rounded-2xl border border-emerald-500/40 bg-card px-5 py-4 shadow-xl">
          <span className="text-3xl leading-none">🎉</span>
          <div className="min-w-0">
            <p className="text-base font-semibold tracking-tight text-foreground">
              Welcome to agentpit! Your wallet is funded.
            </p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {"We've credited your account with apUSD — open any market and place your first trade."}
            </p>
            <a
              href="/#build"
              className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-emerald-600 underline-offset-4 hover:underline dark:text-emerald-400"
            >
              Connect your own trading agent →
            </a>
          </div>
        </div>
      ),
      { position: "top-center", duration: 5000, unstyled: true },
    );
  }, 300);
}
