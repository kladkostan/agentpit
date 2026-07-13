# /get-started Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An investor-demo-grade `/get-started` page (4 personalized steps + a 30-line Python agent), a "Get started →" action on the post-signup toast, and a Settings link.

**Architecture:** Pure snippet builders + a pure `tokenizeSnippet` tinter in `ui/src/lib/getStarted.ts` (one source of truth: the SAME raw string is displayed, tinted, copied, and tested — a lossless-tokenization test guarantees display == clipboard). A reusable `CodeBlock` card owns copy-state; `TintedCode` renders tokens; `GetStartedPage` composes them. `API_BASE_URL` is exported from the existing client.

**Tech Stack:** React/TS + Tailwind (shadcn tokens) + lucide-react + vitest.

**Spec:** `docs/superpowers/specs/2026-07-12-get-started-guide-design.md`

## Global Constraints

- Repo `/Users/yavorsky/dev/agentpit`, branch `mvp`, UI-only. Tree may hold unrelated WIP: NEVER `git add -A` / `git add .` — stage only named files.
- Commands (from `ui/`): `npx vitest run` (currently **126 passed**), `npm run typecheck` (`noUncheckedIndexedAccess: true` — never index arrays unguarded), `npm run lint` (3 pre-existing warnings OK, 0 errors), `npm run build`.
- Git commits: NO `Co-Authored-By` / AI-attribution trailers.
- TDD for the lib (builders + tokenizer); components/pages have no test files (repo pattern).
- **Visual bar is binding (investor demo):** existing design tokens, emerald single accent, light+dark both correct, dark code canvas in both themes, ghost numerals, staggered `agentRise` reveal, copy ✓ feedback. No new fonts, no gradients, no new dependencies.
- Copy button copies the RAW builder string; the lossless-tokenization invariant test pins display == clipboard.
- Logged-out placeholders are exactly `YOUR_API_KEY` and `YOUR_ADDRESS`.

---

### Task 1: Snippet builders + tokenizer (`ui/src/lib/getStarted.ts`)

**Files:**
- Modify: `ui/src/api/client.ts` (export const, no behavior change)
- Create: `ui/src/lib/getStarted.ts`
- Create: `ui/src/lib/getStarted.test.ts`

**Interfaces:**
- Produces (Tasks 2-3 consume verbatim):
  - `export const API_BASE_URL: string` from `@/api/client` (the existing private `BASE_URL`).
  - From `@/lib/getStarted`:
    - `export const KEY_PLACEHOLDER = "YOUR_API_KEY"`, `export const ADDRESS_PLACEHOLDER = "YOUR_ADDRESS"`
    - `registerCurl(base: string): string`, `marketsCurl(base: string): string`, `bookCurl(base: string): string`, `orderCurl(base: string, key: string | null): string`, `positionsCurl(base: string, address: string | null): string`, `agentPy(base: string, key: string | null, address: string | null): string`
    - `export type SnippetToken = { kind: "text" | "comment" | "string" | "chip"; value: string }`
    - `tokenizeSnippet(code: string, chips: string[]): SnippetToken[]` — line-based: a line whose trimmed start is `#` is one `comment` token (newline included); other lines split literal `chips` occurrences first, then same-line quoted spans (`"…"` / `'…'`) as `string` tokens; **lossless**: concatenating token values reproduces the input exactly.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/getStarted.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  ADDRESS_PLACEHOLDER,
  agentPy,
  bookCurl,
  KEY_PLACEHOLDER,
  marketsCurl,
  orderCurl,
  positionsCurl,
  registerCurl,
  tokenizeSnippet,
} from "./getStarted";

const BASE = "http://localhost:8000";

describe("snippet builders", () => {
  it("registerCurl posts email+password to /register", () => {
    const s = registerCurl(BASE);
    expect(s).toContain(`${BASE}/register`);
    expect(s).toContain('"email"');
    expect(s).toContain('"password"');
  });

  it("marketsCurl and bookCurl hit the right endpoints", () => {
    expect(marketsCurl(BASE)).toContain(`${BASE}/markets`);
    expect(bookCurl(BASE)).toContain(`${BASE}/book?token_id=`);
  });

  it("orderCurl interpolates a real key into the X-API-Key header", () => {
    const s = orderCurl(BASE, "pk_live_123");
    expect(s).toContain("X-API-Key: pk_live_123");
    expect(s).toContain(`${BASE}/order`);
    expect(s).toContain('"client_order_id"');
    expect(s).not.toContain(KEY_PLACEHOLDER);
  });

  it("orderCurl falls back to the placeholder without a key", () => {
    expect(orderCurl(BASE, null)).toContain(`X-API-Key: ${KEY_PLACEHOLDER}`);
  });

  it("positionsCurl uses the address (or placeholder) as the user param", () => {
    expect(positionsCurl(BASE, "0xAbC")).toContain("/positions?user=0xAbC");
    expect(positionsCurl(BASE, null)).toContain(
      `/positions?user=${ADDRESS_PLACEHOLDER}`,
    );
  });

  it("agentPy is wired to the real API surface", () => {
    const s = agentPy(BASE, "pk_live_123", "0xAbC");
    expect(s).toContain(`BASE = "${BASE}"`);
    expect(s).toContain('KEY  = "pk_live_123"');
    expect(s).toContain("X-API-Key");
    expect(s).toContain("clobTokenIds");
    expect(s).toContain("client_order_id");
    expect(s).toContain('params={"user": "0xAbC"}');
  });

  it("agentPy uses placeholders when logged out", () => {
    const s = agentPy(BASE, null, null);
    expect(s).toContain(`KEY  = "${KEY_PLACEHOLDER}"`);
    expect(s).toContain(`params={"user": "${ADDRESS_PLACEHOLDER}"}`);
  });
});

describe("tokenizeSnippet", () => {
  it("classifies a whole # line as one comment token, newline included", () => {
    const t = tokenizeSnippet("a\n# note\nb", []);
    expect(t).toContainEqual({ kind: "comment", value: "# note\n" });
  });

  it("wraps chip occurrences and keeps surrounding text", () => {
    const t = tokenizeSnippet("key=pk_1 end", ["pk_1"]);
    expect(t).toEqual([
      { kind: "text", value: "key=" },
      { kind: "chip", value: "pk_1" },
      { kind: "text", value: " end" },
    ]);
  });

  it("tints same-line quoted spans as strings", () => {
    const t = tokenizeSnippet('say "hi" now', []);
    expect(t).toContainEqual({ kind: "string", value: '"hi"' });
  });

  it("prefers chips over string tinting when a chip sits inside quotes", () => {
    const t = tokenizeSnippet('u = "0xAbC"', ["0xAbC"]);
    expect(t).toContainEqual({ kind: "chip", value: "0xAbC" });
    expect(t.filter((x) => x.kind === "string")).toEqual([]);
  });

  it("is LOSSLESS on every builder output (display == clipboard)", () => {
    const key = "pk_live_123";
    const addr = "0xAbC";
    const snippets = [
      registerCurl(BASE),
      marketsCurl(BASE),
      bookCurl(BASE),
      orderCurl(BASE, key),
      orderCurl(BASE, null),
      positionsCurl(BASE, addr),
      agentPy(BASE, key, addr),
      agentPy(BASE, null, null),
    ];
    for (const code of snippets) {
      const glued = tokenizeSnippet(code, [key, addr, KEY_PLACEHOLDER, ADDRESS_PLACEHOLDER])
        .map((t) => t.value)
        .join("");
      expect(glued).toBe(code);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/yavorsky/dev/agentpit/ui && npx vitest run src/lib/getStarted.test.ts`
Expected: FAIL — module `./getStarted` does not exist.

- [ ] **Step 3: Implement**

In `ui/src/api/client.ts`, directly after the `BASE_URL` const definition, add:

```ts
/** Absolute API origin — exported for the /get-started guide's copyable
 *  snippets, so they always target the same host `apiFetch` uses. */
export const API_BASE_URL = BASE_URL;
```

Create `ui/src/lib/getStarted.ts`:

```ts
/** Snippet builders + tinting tokenizer for the /get-started guide.
 *
 *  One source of truth: each builder returns the RAW string that is (a) shown,
 *  (b) copied to the clipboard, and (c) tested. `tokenizeSnippet` splits that
 *  same string into display tokens (comment / string / chip / text) and is
 *  LOSSLESS — concatenating token values reproduces the input — so what the
 *  user sees is byte-identical to what the copy button gives them. */

export const KEY_PLACEHOLDER = "YOUR_API_KEY";
export const ADDRESS_PLACEHOLDER = "YOUR_ADDRESS";

export function registerCurl(base: string): string {
  return `curl -X POST ${base}/register \\
  -H 'Content-Type: application/json' \\
  -d '{"email": "you@example.com", "password": "hunter2hunter2"}'
# → { "user": { "api_key": "…", "eth_address": "0x…" } } — funded and ready`;
}

export function marketsCurl(base: string): string {
  return `curl '${base}/markets?limit=5'
# each market carries clobTokenIds — ["YES", "NO"] token ids you trade`;
}

export function bookCurl(base: string): string {
  return `curl '${base}/book?token_id=TOKEN_ID'
# → { "bids": [...], "asks": [...] } — pick your price off the book`;
}

export function orderCurl(base: string, key: string | null): string {
  return `curl -X POST ${base}/order \\
  -H 'X-API-Key: ${key ?? KEY_PLACEHOLDER}' \\
  -H 'Content-Type: application/json' \\
  -d '{
    "token_id": "TOKEN_ID",
    "side": "BUY",
    "price": 0.42,
    "size": 10,
    "order_type": "GTC",
    "client_order_id": "my-agent-0001"
  }'
# client_order_id makes retries safe — the same id can never double-fill`;
}

export function positionsCurl(base: string, address: string | null): string {
  const addr = address ?? ADDRESS_PLACEHOLDER;
  return `curl '${base}/positions?user=${addr}'
curl '${base}/value?user=${addr}'
# public by address — point a dashboard at it, no key needed`;
}

export function agentPy(
  base: string,
  key: string | null,
  address: string | null,
): string {
  return `"""A complete agentpit agent: pick a market, read the book, trade it."""
import json, random, time, requests

BASE = "${base}"
KEY  = "${key ?? KEY_PLACEHOLDER}"
H    = {"X-API-Key": KEY}

def mid(book):
    bid = float(book["bids"][0]["price"]) if book.get("bids") else 0.0
    ask = float(book["asks"][0]["price"]) if book.get("asks") else 1.0
    return (bid + ask) / 2

# 1) find something worth trading
markets = requests.get(f"{BASE}/markets", params={"limit": 25}).json()
m = random.choice([x for x in markets if x.get("acceptingOrders")])
yes_token = json.loads(m["clobTokenIds"])[0]

# 2) quote it
book = requests.get(f"{BASE}/book", params={"token_id": yes_token}).json()
p = mid(book)
print(f"{m['question']}  YES mid = {p:.3f}")

# 3) your alpha goes here — we just bid one cent under mid
order = requests.post(f"{BASE}/order", headers=H, json={
    "token_id": yes_token,
    "side": "BUY",
    "price": round(max(0.001, p - 0.01), 3),
    "size": 10,
    "order_type": "GTC",
    "client_order_id": f"my-agent-{int(time.time())}",
}).json()
print("order:", order)

# 4) see what you hold
positions = requests.get(f"{BASE}/positions",
                         params={"user": "${address ?? ADDRESS_PLACEHOLDER}"}).json()
print(f"open positions: {len(positions)}")`;
}

/* -------------------------------------------------- display tokenizer --- */

export type SnippetToken = {
  kind: "text" | "comment" | "string" | "chip";
  value: string;
};

/** Split a snippet into display tokens. Line-based: a line whose trimmed
 *  start is '#' becomes one comment token (trailing newline included); other
 *  lines yield chip tokens for literal `chips` occurrences (checked BEFORE
 *  string tinting so a chip inside quotes stays a chip), then same-line
 *  quoted spans as string tokens. Lossless by construction. */
export function tokenizeSnippet(code: string, chips: string[]): SnippetToken[] {
  const out: SnippetToken[] = [];
  const real = chips.filter((c) => c.length > 0);
  const lines = code.split("\n");
  lines.forEach((line, i) => {
    const text = i < lines.length - 1 ? `${line}\n` : line;
    if (line.trimStart().startsWith("#")) {
      out.push({ kind: "comment", value: text });
    } else {
      pushChipSplit(text, real, out);
    }
  });
  return out;
}

function pushChipSplit(text: string, chips: string[], out: SnippetToken[]): void {
  const hit = chips
    .map((c) => ({ c, i: text.indexOf(c) }))
    .filter((h) => h.i >= 0)
    .sort((a, b) => a.i - b.i)[0];
  if (!hit) {
    pushStringSplit(text, out);
    return;
  }
  pushStringSplit(text.slice(0, hit.i), out);
  out.push({ kind: "chip", value: hit.c });
  pushChipSplit(text.slice(hit.i + hit.c.length), chips, out);
}

const QUOTED = /("[^"\n]*"|'[^'\n]*')/g;

function pushStringSplit(text: string, out: SnippetToken[]): void {
  if (!text) return;
  let last = 0;
  for (const m of text.matchAll(QUOTED)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ kind: "text", value: text.slice(last, i) });
    out.push({ kind: "string", value: m[0] });
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
}
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd /Users/yavorsky/dev/agentpit/ui && npx vitest run src/lib/getStarted.test.ts && npm run typecheck`
Expected: PASS (12 new tests), typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/api/client.ts ui/src/lib/getStarted.ts ui/src/lib/getStarted.test.ts
git commit -m "feat(ui): get-started snippet builders + lossless tint tokenizer"
```

---

### Task 2: `CodeBlock` + `TintedCode` components

**Files:**
- Create: `ui/src/components/CodeBlock.tsx`

**Interfaces:**
- Consumes: `tokenizeSnippet`, `type SnippetToken` (Task 1); `cn` from `@/lib/utils`; `Check`, `Copy` from `lucide-react` (existing dependency).
- Produces (Task 3 consumes):
  - `CodeBlock({ title, code, chips, className }: { title: string; code: string; chips?: string[]; className?: string })` — dark-canvas card (dark in BOTH themes), header with title chip + copy button (✓ for 1.5s), body renders the tinted code itself.
  - (internal) `TintedCode` maps tokens → spans: comment `italic text-slate-500`, string `text-emerald-300/90`, chip `rounded bg-emerald-500/15 px-1 py-0.5 font-semibold text-emerald-300`, text plain.

No unit tests (presentational; the tokenizer it delegates to is fully tested) — verified by Task 4's chain + screenshots.

- [ ] **Step 1: Implement**

Create `ui/src/components/CodeBlock.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { tokenizeSnippet } from "@/lib/getStarted";
import { cn } from "@/lib/utils";

/** Dark-canvas code card (dark in BOTH themes — code reads best on ink).
 *  `code` is the single source of truth: it is tokenized for display AND
 *  copied verbatim, so what the user sees is exactly what they paste. */
export function CodeBlock({
  title,
  code,
  chips = [],
  className,
}: {
  title: string;
  code: string;
  chips?: string[];
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be unavailable (http, permissions) — fail quiet.
    }
  };

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-slate-700/60 bg-slate-950 shadow-sm",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="font-mono text-[11px] uppercase tracking-widest text-slate-500">
          {title}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors",
            copied
              ? "text-emerald-400"
              : "text-slate-400 hover:bg-slate-800 hover:text-slate-200",
          )}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-slate-200">
        <TintedCode code={code} chips={chips} />
      </pre>
    </div>
  );
}

function TintedCode({ code, chips }: { code: string; chips: string[] }) {
  return (
    <>
      {tokenizeSnippet(code, chips).map((t, i) =>
        t.kind === "comment" ? (
          <span key={i} className="italic text-slate-500">
            {t.value}
          </span>
        ) : t.kind === "string" ? (
          <span key={i} className="text-emerald-300/90">
            {t.value}
          </span>
        ) : t.kind === "chip" ? (
          <span
            key={i}
            className="rounded bg-emerald-500/15 px-1 py-0.5 font-semibold text-emerald-300"
          >
            {t.value}
          </span>
        ) : (
          <span key={i}>{t.value}</span>
        ),
      )}
    </>
  );
}
```

- [ ] **Step 2: Typecheck + lint**

Run: `cd /Users/yavorsky/dev/agentpit/ui && npm run typecheck && npm run lint`
Expected: clean / 0 errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/components/CodeBlock.tsx
git commit -m "feat(ui): CodeBlock — dark code card, tinted from the copyable source"
```

---

### Task 3: `GetStartedPage` + route

**Files:**
- Create: `ui/src/pages/GetStartedPage.tsx`
- Modify: `ui/src/App.tsx` (one route)

**Interfaces:**
- Consumes: Task 1 builders + placeholders + `API_BASE_URL`; Task 2 `CodeBlock`; `useAuth` from `@/auth/useAuth` (`user: { api_key, eth_address } | null`, `openSignup`); `Button` from `@/components/ui/button`; `Link` from react-router-dom; `ArrowRight`, `KeyRound`, `Wallet` from lucide-react.
- Produces: route `/get-started` (Task 4 links to it).

No unit tests (page; repo pattern). All copyable text comes from tested builders.

- [ ] **Step 1: Implement the page**

Create `ui/src/pages/GetStartedPage.tsx`:

```tsx
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
```

- [ ] **Step 2: Add the route**

In `ui/src/App.tsx`: import `GetStartedPage` alongside the other page imports and add, next to the existing `/agents` routes:

```tsx
<Route path="/get-started" element={<GetStartedPage />} />
```

- [ ] **Step 3: Verify — suite, typecheck, lint, build**

Run: `cd /Users/yavorsky/dev/agentpit/ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all pass (vitest = Task 1's count), lint 0 errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/pages/GetStartedPage.tsx ui/src/App.tsx
git commit -m "feat(ui): /get-started — personalized connect-your-agent guide"
```

---

### Task 4: Entry points + visual verification

**Files:**
- Modify: `ui/src/auth/AuthContext.tsx` (welcome toast gains the offer)
- Modify: `ui/src/pages/SettingsPage.tsx` (link near ApiKeyRow)

**Interfaces:**
- Consumes: route `/get-started` (Task 3).

- [ ] **Step 1: Extend the welcome toast**

In `ui/src/auth/AuthContext.tsx`, inside the `toast.custom` JSX (lines ~145-155), after the existing `<p className="mt-1 …">…</p>` paragraph, add (plain `<a>` — the toast portal renders outside the Router, so `Link` is unavailable):

```tsx
                <a
                  href="/get-started"
                  className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-emerald-600 underline-offset-4 hover:underline dark:text-emerald-400"
                >
                  Connect your own trading agent →
                </a>
```

- [ ] **Step 2: Settings link**

In `ui/src/pages/SettingsPage.tsx`, directly after the `<ApiKeyRow apiKey={user.api_key} />` line (line ~46), add:

```tsx
            <p className="text-xs text-muted-foreground">
              Building a bot?{" "}
              <Link
                to="/get-started"
                className="font-medium text-emerald-600 underline-offset-4 hover:underline dark:text-emerald-400"
              >
                Connect your own agent — 4-step guide
              </Link>
            </p>
```

Add `import { Link } from "react-router-dom";` if the file doesn't already import it.

- [ ] **Step 3: Verify — full chain**

Run: `cd /Users/yavorsky/dev/agentpit/ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all pass.

- [ ] **Step 4: Visual verification (only if http://localhost:5173 already responds — do NOT start servers)**

With Playwright: open `/get-started` at 1440×900, screenshot; switch the app to the other theme (theme toggle or `document.documentElement` class) and screenshot again. Check: hero + ghost numerals + dark code cards render in BOTH themes; no horizontal page scroll; copy button flips to "Copied ✓" on click; logged-out snippets show `YOUR_API_KEY` chips. Note results (or "dev server not running — skipped") in the report.

- [ ] **Step 5: Commit**

```bash
cd /Users/yavorsky/dev/agentpit
git add ui/src/auth/AuthContext.tsx ui/src/pages/SettingsPage.tsx
git commit -m "feat(ui): get-started entry points — signup toast offer + settings link"
```
