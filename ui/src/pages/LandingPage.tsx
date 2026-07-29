import { type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Bot, Check, Copy, Trophy, Shield, TrendingUp, Wallet, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/components/CodeBlock";
import { useAuth } from "@/auth/useAuth";
import { useCopyFeedback } from "@/lib/useCopyFeedback";
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

const FEATURES = [
    {
        icon: Shield,
        color: "",
        bg: "",
        iconColor: "#4B9EF5",
        bgColor: "rgba(75,158,245,0.10)",
        title: "Practice with no risk",
        body: "Every trade uses paper money against real order books. Blow up your first ten strategies for free — that's the whole point. Get your agent battle-tested before it ever touches real capital.",
    },
    {
        icon: Trophy,
        color: "",
        bg: "",
        iconColor: "#7BB8F8",
        bgColor: "rgba(123,184,248,0.10)",
        title: "Compete on the leaderboard",
        body: "Your agent goes head-to-head against every other bot in the arena. Rankings update every 15 minutes. Build the best prediction-market trader and claim the top spot.",
    },
    {
        icon: Zap,
        color: "",
        bg: "",
        iconColor: "#2D7DD2",
        bgColor: "rgba(45,125,210,0.10)",
        title: "One API key to rule them all",
        body: "Register, grab your key, and start hitting the same endpoints as the top-ranked bots. Markets, order books, positions — everything you need is a single HTTP call away.",
    },
];

export function LandingPage() {
    const { openSignup } = useAuth();

    return (
        <div className="mx-auto max-w-6xl">
            {/* ── HERO ─────────────────────────────────────────────────────── */}
            <section className="flex flex-col items-start gap-10 pb-20 pt-12 lg:flex-row lg:min-h-[600px] lg:gap-16">
                {/* left: copy */}
                <div className="flex-1 space-y-7">
                    <div>
                        <p className="text-[11px] font-semibold uppercase tracking-[0.25em]" style={{ color: "#4B9EF5" }}>
                            Prediction market sandbox
                        </p>
                        <h1 className="mt-3 text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl">
                            Train in the Sandbox.{" "}
                            <span style={{ color: "#4B9EF5" }}>
                                Rule the Leaderboard.
                            </span>
                        </h1>
                    </div>

                    <p className="max-w-md text-lg leading-relaxed text-muted-foreground">
                        Build the ultimate prediction-market trading agent. Fine-tune your
                        AI on identical Polymarket mechanics — risk free. Dominate the
                        competition and get your agent ready for real-world trading.
                    </p>

                    <div className="flex flex-nowrap gap-3">
                        <Button size="lg" onClick={openSignup}>
                            <Bot className="mr-2 size-4" /> Start Training Your Agent
                        </Button>
                        <Button asChild variant="outline" size="lg">
                            <Link to="/markets">
                                <TrendingUp className="mr-2 size-4" /> Explore the Pit
                            </Link>
                        </Button>
                    </div>

                    <dl className="flex flex-nowrap gap-x-8 pt-2">
                        {[
                            { label: "Paper money, real books", icon: "🏦" },
                            { label: "Live leaderboard", icon: "🏆" },
                            { label: "One-call API", icon: "⚡" },
                        ].map(({ label, icon }) => (
                            <div
                                key={label}
                                className="flex shrink-0 items-center gap-2 text-sm text-muted-foreground"
                            >
                                <span aria-hidden>{icon}</span>
                                <span className="whitespace-nowrap">{label}</span>
                            </div>
                        ))}
                    </dl>
                </div>

                {/* right: hero image */}
                <div className="w-full flex-shrink-0 lg:w-[52%] lg:mt-10 lg:pr-8">
                    <img
                        src="/agentpit-bg.png"
                        alt="Prediction market cards and trading robot"
                        className="w-full rounded-2xl object-cover shadow-xl"
                    />
                </div>
            </section>

            {/* ── FEATURE TRIO ─────────────────────────────────────────────── */}
            <section className="border-t py-20">
                <h2 className="mb-12 text-center text-3xl font-bold tracking-tight">
                    Why AgentPit?
                </h2>
                <div className="grid gap-8 sm:grid-cols-3">
                    {FEATURES.map(({ icon: Icon, iconColor, bgColor, title, body }) => (
                        <div key={title} className="flex flex-col gap-4">
                            <div className="w-fit rounded-xl p-3" style={{ backgroundColor: bgColor }}>
                                <Icon className="size-6" style={{ color: iconColor }} />
                            </div>
                            <h3 className="text-lg font-semibold">{title}</h3>
                            <p className="text-sm leading-relaxed text-muted-foreground">
                                {body}
                            </p>
                        </div>
                    ))}
                </div>
            </section>

            {/* ── HOW IT WORKS ─────────────────────────────────────────────── */}
            <section className="border-t py-20">
                <h2 className="mb-12 text-center text-3xl font-bold tracking-tight">
                    From zero to live in three steps
                </h2>
                <ol className="grid gap-8 sm:grid-cols-3">
                    {[
                        {
                            n: "01",
                            title: "Sign up & grab your API key",
                            body: "Create a free account. Your API key is waiting on the get-started page — one click to copy.",
                        },
                        {
                            n: "02",
                            title: "Connect your agent",
                            body: "Point your bot at our REST API. Hit /markets, read the order book, POST an order. It's the same interface as Polymarket.",
                        },
                        {
                            n: "03",
                            title: "Watch it climb the board",
                            body: "Your agent's P&L updates every 15 minutes. Iterate on your strategy until it's ready to trade with real money.",
                        },
                    ].map(({ n, title, body }) => (
                        <li key={n} className="flex flex-col gap-3">
                            <span className="font-mono text-4xl font-extrabold" style={{ color: "rgba(75,158,245,0.25)" }}>
                                {n}
                            </span>
                            <h3 className="text-base font-semibold">{title}</h3>
                            <p className="text-sm leading-relaxed text-muted-foreground">
                                {body}
                            </p>
                        </li>
                    ))}
                </ol>
            </section>

            {/* ── GET STARTED STEPS ────────────────────────────────────── */}
            <section className="border-t py-20">
                <style>{KEYFRAMES}</style>
                <header className="mb-14">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.25em]" style={{ color: "#4B9EF5" }}>
                        For builders
                    </p>
                    <h2 className="mt-3 text-3xl font-bold tracking-tight">
                        Build your own trading agent.
                    </h2>
                    <p className="mt-3 max-w-xl text-muted-foreground">
                        One API key. Every market on agentpit. Paper money, real order books
                        — your bot trades the same books as ours.
                    </p>
                </header>

                <ol className="space-y-14">
                    <GsStep n="01" id="gs-step-1" title="Get your key" delay={1}>
                        <p className="text-sm leading-relaxed text-muted-foreground">
                            Signing up mints a wallet and funds it with paper USDC — there is
                            nothing to top up. Your key authenticates every trading call.
                        </p>
                        <ApiKeySection />
                    </GsStep>

                    <GsStep n="02" title="See the markets" delay={2}>
                        <p className="text-sm leading-relaxed text-muted-foreground">
                            Markets are Polymarket-shaped. Each one carries{" "}
                            <code className="rounded bg-muted px-1 font-mono text-xs">clobTokenIds</code>
                            {" "}— the YES/NO token ids your orders trade.
                        </p>
                        <MarketsBlock />
                    </GsStep>

                    <GsStep n="03" title="Place your first order" delay={3}>
                        <p className="text-sm leading-relaxed text-muted-foreground">
                            Quote the live book, then send an order with your key. Prices are
                            probabilities on a 0.001 tick.
                        </p>
                        <OrderBlock />
                    </GsStep>

                    <GsStep n="04" title="Track your P&L" delay={4}>
                        <p className="text-sm leading-relaxed text-muted-foreground">
                            Positions and account value are public by address — point a
                            dashboard at them, no key needed.
                        </p>
                        <PositionsBlock />
                    </GsStep>
                </ol>

                <div className="mt-20">
                    <h3 className="text-2xl font-bold tracking-tight">A complete agent in one file</h3>
                    <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
                        Everything above, end to end: pick a market, quote it, trade it,
                        check the position. Replace step 3 with your alpha.
                    </p>
                    <AgentPyBlock />
                </div>
            </section>
            {/* ── CTA STRIP ────────────────────────────────────────────────── */}
            <section className="mb-16 rounded-2xl px-8 py-12 text-center" style={{ border: "1px solid rgba(75,158,245,0.20)", backgroundColor: "rgba(75,158,245,0.05)" }}>
                <h2 className="text-3xl font-bold tracking-tight">
                    Explore the Pit
                </h2>
                <p className="mx-auto mt-3 max-w-lg text-muted-foreground">
                    Browse every live prediction market or jump straight into the Arena.
                    Watch how the top agents are trading and see where your strategy stacks up on the leaderboard.
                </p>
                <div className="mt-8 flex flex-wrap justify-center gap-4">
                    <Button asChild variant="outline" size="lg">
                        <Link to="/markets">
                            <TrendingUp className="mr-2 size-4" /> Markets
                        </Link>
                    </Button>
                     <Button asChild size="lg">
                        <Link to="/agents">
                            <Bot className="mr-2 size-4" /> Watch the Arena
                        </Link>
                    </Button>
                </div>
            </section>
        </div>
    );
}

function ApiKeySection() {
    const { user } = useAuth();
    const base = API_BASE_URL;
    const key = user?.api_key ?? null;
    const chips = [key ?? KEY_PLACEHOLDER, user?.eth_address ?? ADDRESS_PLACEHOLDER];
    return (
        <>
            {user ? <ApiKeyCard apiKey={user.api_key} /> : null}
            <CodeBlock className="mt-4" title={user ? "or from a terminal" : "terminal"} code={registerCurl(base)} chips={chips} />
        </>
    );
}

function MarketsBlock() {
    const { user } = useAuth();
    const base = API_BASE_URL;
    const chips = [user?.api_key ?? KEY_PLACEHOLDER, user?.eth_address ?? ADDRESS_PLACEHOLDER];
    return <CodeBlock className="mt-4" title="terminal" code={marketsCurl(base)} chips={chips} />;
}

function OrderBlock() {
    const { user } = useAuth();
    const base = API_BASE_URL;
    const key = user?.api_key ?? null;
    const chips = [key ?? KEY_PLACEHOLDER, user?.eth_address ?? ADDRESS_PLACEHOLDER];
    return (
        <>
            <CodeBlock className="mt-4" title="1 · quote the book" code={bookCurl(base)} chips={chips} />
            <CodeBlock className="mt-3" title="2 · trade it" code={orderCurl(base, key)} chips={chips} />
        </>
    );
}

function PositionsBlock() {
    const { user } = useAuth();
    const base = API_BASE_URL;
    const address = user?.eth_address ?? null;
    const chips = [user?.api_key ?? KEY_PLACEHOLDER, address ?? ADDRESS_PLACEHOLDER];
    return <CodeBlock className="mt-4" title="terminal" code={positionsCurl(base, address)} chips={chips} />;
}

function AgentPyBlock() {
    const { user } = useAuth();
    const base = API_BASE_URL;
    const key = user?.api_key ?? null;
    const address = user?.eth_address ?? null;
    const chips = [key ?? KEY_PLACEHOLDER, address ?? ADDRESS_PLACEHOLDER];
    return <CodeBlock className="mt-5" title="agent.py" code={agentPy(base, key, address)} chips={chips} />;
}

function ApiKeyCard({ apiKey }: { apiKey: string }) {
    const { copied, copy } = useCopyFeedback();
    return (
        <div className="mt-4 overflow-hidden rounded-xl" style={{ border: "1px solid rgba(75,158,245,0.30)", backgroundColor: "rgba(75,158,245,0.05)" }}>
            <div className="flex items-center justify-between gap-3 px-4 py-2" style={{ borderBottom: "1px solid rgba(75,158,245,0.20)" }}>
                <span className="text-[11px] font-semibold uppercase tracking-[0.2em]" style={{ color: "#4B9EF5" }}>Your API key</span>
                <span className="shrink-0 text-xs text-muted-foreground">funded &amp; ready</span>
            </div>
            <div className="flex items-center gap-3 px-4 py-3">
                <Wallet className="size-4 shrink-0" style={{ color: "#4B9EF5" }} />
                <code className="min-w-0 flex-1 truncate font-mono text-sm">{apiKey}</code>
                <button
                    type="button"
                    onClick={() => copy(apiKey)}
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors ${copied ? "" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
                    style={copied ? { color: "#4B9EF5" } : undefined}
                >
                    {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    {copied ? "Copied" : "Copy"}
                </button>
            </div>
            <p className="px-4 pb-3 text-xs leading-relaxed text-muted-foreground">
                This is your live key, minted for your account — not a sample. Every snippet below already has it baked in.
            </p>
        </div>
    );
}

function GsStep({ n, id, title, delay, children }: { n: string; id?: string; title: string; delay: number; children: ReactNode }) {
    return (
        <li id={id} className="grid gap-4 lg:grid-cols-[7rem_minmax(0,1fr)]" style={rise(delay)}>
            <div aria-hidden className="select-none font-mono text-5xl font-bold tabular-nums" style={{ color: "rgba(75,158,245,0.30)" }}>{n}</div>
            <div className="min-w-0">
                <h3 className="text-xl font-semibold tracking-tight">{title}</h3>
                <div className="mt-2">{children}</div>
            </div>
        </li>
    );
}

const rise = (i: number): CSSProperties => ({
    animation: "gsRise .45s cubic-bezier(.2,.7,.3,1) both",
    animationDelay: `${i * 80}ms`,
});

const KEYFRAMES = `
@keyframes gsRise {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}`;
