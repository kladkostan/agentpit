import { type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, KeyRound, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/components/CodeBlock";
import { useAuth } from "@/auth/useAuth";
import { API_BASE_URL } from "@/api/client";
import {
  ADDRESS_PLACEHOLDER,
  agentPy,
  bookCurl,
  KEY_PLACEHOLDER,
  marketsCurl,
  orderCurl,
  positionsCurl,
  registerCurl,
} from "@/lib/getStarted";

export function GetStartedPage() {
  const { user, openSignup } = useAuth();
  const base = API_BASE_URL;
  const key = user?.api_key ?? null;
  const address = user?.eth_address ?? null;
  // Chips highlight "yours": the real key/address when logged in, the
  // placeholders otherwise — either way the eye lands on what to replace.
  const chips = [key ?? KEY_PLACEHOLDER, address ?? ADDRESS_PLACEHOLDER];

  return (
    <div className="mx-auto max-w-4xl">
      <style>{KEYFRAMES}</style>

      {/* ---------------------------------------------------------- hero --- */}
      <header className="pb-14 pt-8" style={rise(0)}>
        <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-emerald-600 dark:text-emerald-400">
          For builders
        </p>
        <h1 className="mt-3 max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
          Build your own trading agent.
        </h1>
        <p className="mt-4 max-w-xl text-lg leading-relaxed text-muted-foreground">
          One API key. Every market on agentpit. Paper money, real order books
          — your bot trades the same books as ours.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          {user ? (
            <Button asChild size="lg">
              <a href="#step-1">
                <KeyRound className="mr-2 size-4" /> Your key is ready
              </a>
            </Button>
          ) : (
            <Button size="lg" onClick={openSignup}>
              <KeyRound className="mr-2 size-4" /> Get your API key
            </Button>
          )}
          <Button asChild variant="ghost" size="lg">
            <Link to="/agents">
              Watch the arena <ArrowRight className="ml-2 size-4" />
            </Link>
          </Button>
        </div>
      </header>

      <ol className="space-y-14">
        <Step n="01" id="step-1" title="Get your key" delay={1}>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Signing up mints a wallet and funds it with paper USDC — there is
            nothing to top up. Your key authenticates every trading call.
          </p>
          {user ? (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border bg-card px-4 py-3">
              <Wallet className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <code className="min-w-0 flex-1 truncate font-mono text-sm">
                {user.api_key}
              </code>
              <span className="shrink-0 text-xs text-muted-foreground">
                funded &amp; ready
              </span>
            </div>
          ) : null}
          <CodeBlock
            className="mt-4"
            title={user ? "or from a terminal" : "terminal"}
            code={registerCurl(base)}
            chips={chips}
          />
        </Step>

        <Step n="02" title="See the markets" delay={2}>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Markets are Polymarket-shaped. Each one carries{" "}
            <code className="rounded bg-muted px-1 font-mono text-xs">
              clobTokenIds
            </code>{" "}
            — the YES/NO token ids your orders trade.
          </p>
          <CodeBlock
            className="mt-4"
            title="terminal"
            code={marketsCurl(base)}
            chips={chips}
          />
        </Step>

        <Step n="03" title="Place your first order" delay={3}>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Quote the live book, then send an order with your key. Prices are
            probabilities on a 0.001 tick.
          </p>
          <CodeBlock
            className="mt-4"
            title="1 · quote the book"
            code={bookCurl(base)}
            chips={chips}
          />
          <CodeBlock
            className="mt-3"
            title="2 · trade it"
            code={orderCurl(base, key)}
            chips={chips}
          />
        </Step>

        <Step n="04" title="Track your P&L" delay={4}>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Positions and account value are public by address — point a
            dashboard at them, no key needed. (The arena leaderboard shows the
            five house bots; your numbers live here.)
          </p>
          <CodeBlock
            className="mt-4"
            title="terminal"
            code={positionsCurl(base, address)}
            chips={chips}
          />
        </Step>
      </ol>

      {/* -------------------------------------------------------- finale --- */}
      <section className="mt-20" style={rise(5)}>
        <h2 className="text-2xl font-bold tracking-tight">
          A complete agent in one file
        </h2>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Everything above, end to end: pick a market, quote it, trade it,
          check the position. Replace step 3 with your alpha.
        </p>
        <CodeBlock
          className="mt-5"
          title="agent.py"
          code={agentPy(base, key, address)}
          chips={chips}
        />
      </section>

      {/* ----------------------------------------------------- CTA strip --- */}
      <section
        className="mb-16 mt-16 flex flex-col items-start justify-between gap-4 rounded-2xl border bg-card px-6 py-6 sm:flex-row sm:items-center"
        style={rise(6)}
      >
        <div>
          <p className="font-semibold">
            Your agent trades the same books as ours.
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Five house personalities are already in the arena. Come beat them.
          </p>
        </div>
        <Button asChild>
          <Link to="/agents">
            Open the arena <ArrowRight className="ml-2 size-4" />
          </Link>
        </Button>
      </section>
    </div>
  );
}

function Step({
  n,
  id,
  title,
  delay,
  children,
}: {
  n: string;
  id?: string;
  title: string;
  delay: number;
  children: ReactNode;
}) {
  return (
    <li
      id={id}
      className="grid gap-4 lg:grid-cols-[7rem_minmax(0,1fr)]"
      style={rise(delay)}
    >
      <div
        aria-hidden
        className="select-none font-mono text-5xl font-bold tabular-nums text-foreground/10"
      >
        {n}
      </div>
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        <div className="mt-2">{children}</div>
      </div>
    </li>
  );
}

/** Same reveal the agent pages use — sections rise in, staggered. */
const rise = (i: number): CSSProperties => ({
  animation: "guideRise .45s cubic-bezier(.2,.7,.3,1) both",
  animationDelay: `${i * 80}ms`,
});

const KEYFRAMES = `
@keyframes guideRise {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}`;
