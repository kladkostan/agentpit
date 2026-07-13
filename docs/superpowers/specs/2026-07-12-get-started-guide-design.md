# /get-started — "Connect your agent" Guide — Design

**Date:** 2026-07-12 · **Repo:** agentpit, branch `mvp` (UI-only) · **Status:** approved by user (form: page + post-signup offer; bar: investor-demo quality — "чтобы наш CEO мог показывать это потенциальным инвесторам")

## Goal

A `/get-started` page that takes an outside user from zero to a trading agent
in four steps, personalized with their real API key — polished enough to be a
pitch surface in an investor demo. Plus a post-signup offer pointing at it and
a link from Settings.

## Verified facts (the guide's whole premise)

- `POST /register {email, password}` returns `user.api_key` + `user.eth_address`
  and **auto-onboards on-chain**: paper-USDC faucet drip, gas grant, approvals
  (`auth_service._run_onboarding`). There is NO separate funding step — the
  user's hypothesis "нужен только api ключ" is correct.
- Auth for trading calls = `X-API-Key: <key>` header (same as our arena bots).
- Endpoints an agent needs: `GET /markets` (Gamma shape; `clobTokenIds` is a
  JSON-encoded string array — YES token first), `GET /book?token_id=`,
  `POST /order {token_id, side: BUY|SELL, price (0<p<1, 0.001 tick), size,
  order_type: GTC, client_order_id?}`, `GET /positions?user=<address>` and
  `GET /value?user=<address>` (public by address, no key).
- UI already has: client-side `user.api_key` + `eth_address` in AuthContext;
  API base URL const in `ui/src/api/client.ts` (private — will be exported);
  a post-register welcome toast in `AuthContext.register` (AuthContext.tsx:142-159);
  `ApiKeyRow` on SettingsPage (SettingsPage.tsx:46,184).

## Page structure (`/get-started`)

1. **Hero** — kicker `FOR BUILDERS`, h1 "Build your own trading agent.",
   sub "One API key. Every market on agentpit. Paper money, real order books."
   CTAs: primary **Get your API key** (logged-out → opens signup dialog;
   logged-in → scrolls to step 1 where the key is shown), secondary link
   **Watch the arena →** (`/agents`).
2. **Step 01 — Get your key.** Logged-in: the user's REAL `api_key` in a
   copyable chip + one line "your wallet is already funded with paper USDC —
   nothing to top up". Logged-out: Sign-up button + equivalent
   `curl POST /register` snippet for terminal people.
3. **Step 02 — See the markets.** `curl GET /markets` snippet + one-line
   explanation: each market carries YES/NO token ids (`clobTokenIds`) — that's
   what you trade.
4. **Step 03 — Place your first order.** `curl GET /book?token_id=…` then
   `curl POST /order` with `X-API-Key`; note that `client_order_id` makes
   retries safe.
5. **Step 04 — Track your P&L.** `curl GET /positions?user=<their address>`
   and `GET /value?user=<address>`; honest note: the `/agents` leaderboard
   currently shows the five house bots — your results live in the API.
6. **Finale — "A complete agent in one file."** A correct ~30-line Python
   script (requests only): pick an open market → parse `clobTokenIds` → book
   mid → `POST /order` one tick below mid → print positions. Copy-paste-run.
7. **Closing CTA strip** — "Your agent trades the same books as ours." +
   button to `/agents`.

**Personalization:** logged-in users see their real `api_key` (highlighted
chip inside snippets) and real `eth_address`; logged-out see `YOUR_API_KEY` /
`YOUR_ADDRESS` placeholders. Copy always copies the raw snippet text.

## Visual direction (investor-demo bar — binding, concrete)

- **Reads as THIS product**, not a docs site: existing shadcn/Tailwind tokens
  (`bg-card`, `text-muted-foreground`, `rounded-2xl border`), emerald as the
  single accent, full light+dark support, no new fonts, no gradients.
- **Oversized ghost step numerals** (`01…04`, ~text-5xl, `text-foreground/10`)
  in a `lg:grid-cols-[7rem_1fr]` step grid; generous vertical rhythm
  (`space-y-16`); mobile stacks cleanly.
- **Code cards on a dark canvas in BOTH themes** (slate-950-style), rounded-xl,
  header bar with a language/filename chip and a **Copy button with ✓
  feedback** (lucide `Copy`→`Check`, ~1.5s). Mono 13px, `overflow-x-auto`.
- **Hand-tinted highlighting** — snippets are static authored JSX, so no
  highlighter dependency: comments slate-500 italic, strings emerald-300,
  everything else slate-200. The API key renders as an **emerald token chip**
  (`bg-emerald-500/15 text-emerald-300 rounded px-1`) — the personalized
  "that's MY key" demo moment.
- **Load motion:** staggered rise per section (the `agentRise` keyframe
  pattern already used by AgentPage, `animation-delay: i*80ms`).
- Wide snippets scroll inside their card; the page body never scrolls
  horizontally.

## Entry points

- **Post-signup offer:** extend the existing welcome toast
  (AuthContext.register) with a "Get started →" action linking `/get-started`
  (plain `<a>` — the toast portal may render outside the Router). Login (not
  register) shows no offer, as today.
- **Settings:** a "Connect your own agent → guide" link next to `ApiKeyRow`.
- **Route:** `/get-started` in App.tsx. No TopNav change (offer + settings
  cover discovery; nav stays uncluttered).

## Architecture

- `ui/src/lib/getStarted.ts` — pure, tested snippet builders:
  `registerCurl(base)`, `marketsCurl(base)`, `bookCurl(base)`,
  `orderCurl(base, key)`, `positionsCurl(base, address)`,
  `agentPy(base, key, address)` — all return the RAW string used for copy and
  for tests; `key`/`address` are `string | null` (null → placeholders).
- `ui/src/components/CodeBlock.tsx` — presentational card: props
  `{ title, code (raw for copy), children (tinted JSX) }`, owns the
  copy-button state. Reused by every step.
- `ui/src/pages/GetStartedPage.tsx` — hero + steps + finale; reads
  `useAuth().user` for key/address; renders tinted JSX per snippet.
- `ui/src/api/client.ts` — export the existing base-URL const as
  `API_BASE_URL` (no behavior change).

## Testing

- Vitest on the builders: real key/address interpolated; null → placeholders;
  base URL respected (no trailing slash issues); the python script contains
  `X-API-Key`, `client_order_id`, and parses `clobTokenIds`.
- Page/toast/CodeBlock: no component tests (repo pattern); verified by
  typecheck + lint + build + Playwright screenshots (light AND dark) when the
  dev server is already running.

## Out of scope

- External agents on the `/agents` leaderboard (separate feature).
- A full endpoint reference; interactive "we see your first order" wizard.
- Any backend change.
