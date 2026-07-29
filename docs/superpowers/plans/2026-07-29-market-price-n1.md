# Market probabilities without the book fan-out — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the UI from fetching one order book per market to display a probability — the price is already in the list payload — cutting the home page from ~210 API requests to ~7 and the event page from ~70 to ~7.

**Architecture:** `gammaToMarket` currently discards the server's `outcomePrices` / `bestBid` / `bestAsk`, so four display paths re-derive them with one `GET /book` per market. The fix threads those fields onto the UI `Market` type, adds one pure helper for the per-market price map, rewrites the four call sites to read from the market object, and deletes the now-unused book hooks. Because the price no longer arrives on a 30 s book poll, the two detail-page queries gain their own 30 s refetch.

**Tech Stack:** React 19 + TypeScript, TanStack Query, Vitest, Vite. UI-only — no backend change.

## Global Constraints

- Branch `mvp`, repo `/Users/yavorsky/dev/agentpit`. UI-only: nothing under `agentpit/` changes.
- Verify chain after every task, all four must pass: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`. `npm run lint` has 3 pre-existing `react-refresh/only-export-components` warnings (badge.tsx, button.tsx, searchContext.tsx) — those are expected; **0 errors** is the bar.
- `tsconfig` sets `noUncheckedIndexedAccess: true`: indexing an array yields `T | undefined`. Never index without a guard or `??` fallback. Vitest does NOT typecheck — `npm run typecheck` is mandatory.
- Server contract, verified in `agentpit/polymarket/pricing.py:17-28` — do not re-derive it: `outcome_prices` holds one price per outcome aligned to `erc1155_tokens`; `best_bid` / `best_ask` / `last_trade` describe **outcome[0] (YES)** only. `0.0` means "no resting order on that side", not a real price.
- Stage only the files named in each task. NEVER `git add -A` or `git add .`.
- No `Co-Authored-By` or any AI-attribution trailer in commit messages.

---

### Task 1: Carry prices on the Market type

**Files:**
- Modify: `ui/src/types/market.ts:10-25` (the `Market` interface)
- Modify: `ui/src/api/markets.ts:1-34` (imports + `gammaToMarket`)
- Modify: `ui/src/lib/eventOutcomes.ts` (add `yesPriceMap`, `buyChipCents`)
- Test: `ui/src/api/markets.test.ts` (append a describe block)
- Test: `ui/src/lib/eventOutcomes.test.ts` (fixture + new describes)
- Modify (fixtures only): `ui/src/lib/eventChartSeries.test.ts:7-15`, `ui/src/lib/rotatingSeries.test.ts:13-21`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Market.outcome_prices: number[]`, `Market.best_bid: number | null`, `Market.best_ask: number | null`; `yesPriceMap(markets: readonly Market[]): ReadonlyMap<number, number>`; `buyChipCents(market: Market): { yes: number | null; no: number | null }`.

- [ ] **Step 1: Write the failing tests**

Append to `ui/src/api/markets.test.ts`:

```ts
describe("gammaToMarket prices", () => {
  it("maps outcomePrices into numbers, in order", () => {
    const m = gammaToMarket({ ...baseGamma, outcomePrices: '["0.16","0.84"]' });
    expect(m.outcome_prices).toEqual([0.16, 0.84]);
  });

  it("yields [] for empty, malformed or non-numeric prices", () => {
    for (const raw of ["[]", "", "not json", '["a","b"]', '{"a":1}']) {
      expect(
        gammaToMarket({ ...baseGamma, outcomePrices: raw }).outcome_prices,
      ).toEqual([]);
    }
  });

  it("treats a 0.0 touch as 'no book' and passes real quotes through", () => {
    const none = gammaToMarket({ ...baseGamma, bestBid: 0, bestAsk: 0 });
    expect(none.best_bid).toBeNull();
    expect(none.best_ask).toBeNull();

    const quoted = gammaToMarket({ ...baseGamma, bestBid: 0.14, bestAsk: 0.18 });
    expect(quoted.best_bid).toBeCloseTo(0.14, 5);
    expect(quoted.best_ask).toBeCloseTo(0.18, 5);
  });
});
```

`ui/src/lib/eventOutcomes.test.ts` already has a local factory named **`m`** with the
signature `function m(id: number, label = \`m${id}\`): Market`. Keep that name and its
existing `label` parameter; add a THIRD parameter for the price and the three new
fields to the object it returns (keep every field it already has):

```ts
function m(id: number, label = `m${id}`, yesPrice: number | null = null): Market {
  return {
    // ...every existing field unchanged...
    outcome_prices: yesPrice === null ? [] : [yesPrice, 1 - yesPrice],
    best_bid: null,
    best_ask: null,
  };
}
```

Then append:

```ts
describe("yesPriceMap", () => {
  it("keys the YES price by market id", () => {
    const map = yesPriceMap([m(1, "a", 0.62), m(2, "b", 0.11)]);
    expect(map.get(1)).toBeCloseTo(0.62, 5);
    expect(map.get(2)).toBeCloseTo(0.11, 5);
  });

  it("omits markets with no usable price so they sort last", () => {
    const map = yesPriceMap([m(1, "a", 0.62), m(2, "b", null)]);
    expect(map.has(2)).toBe(false);
    expect(map.size).toBe(1);
  });
});

describe("buyChipCents", () => {
  it("prices YES at its own ask and NO through the YES bid", () => {
    const { yes, no } = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: 0.6,
      best_ask: 0.64,
    });
    expect(yes).toBeCloseTo(64, 5);
    expect(no).toBeCloseTo(40, 5);
  });

  it("returns null per side when that side has no resting order", () => {
    const { yes, no } = buyChipCents({
      ...m(1, "a", 0.62),
      best_bid: null,
      best_ask: null,
    });
    expect(yes).toBeNull();
    expect(no).toBeNull();
  });
});
```

Add `yesPriceMap` and `buyChipCents` to that file's existing import from `./eventOutcomes`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && npx vitest run src/api/markets.test.ts src/lib/eventOutcomes.test.ts`
Expected: FAIL — `yesPriceMap`/`buyChipCents` are not exported, and `outcome_prices` is undefined on the mapped market.

- [ ] **Step 3: Add the fields to the Market type**

In `ui/src/types/market.ts`, inside `interface Market`, after `icon_url: string | null;`:

```ts
  /** One probability in [0, 1] per outcome, index-aligned with
   *  `erc1155_tokens`. Empty when the payload carried no usable prices. */
  outcome_prices: number[];
  /** Best bid / ask for outcome[0] (YES) in [0, 1] — the server ships exactly
   *  one pair per market (Gamma parity). `null` means no resting order on that
   *  side; the wire sends 0.0 for that case and it must not reach the UI as a
   *  real 0¢ quote. */
  best_bid: number | null;
  best_ask: number | null;
```

- [ ] **Step 4: Map them in `gammaToMarket`**

In `ui/src/api/markets.ts`, above `gammaToMarket`:

```ts
/** Parse Gamma's JSON-encoded price array (e.g. `'["0.16","0.84"]'`). These
 *  values are presentational, so any malformed input yields [] instead of
 *  throwing — a bad payload must never blank a page. */
function parseOutcomePrices(raw: string | null | undefined): number[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const nums = parsed.map((p) => Number(p));
    return nums.every((n) => Number.isFinite(n)) ? nums : [];
  } catch {
    return [];
  }
}

/** The wire uses 0.0 for "no resting order on this side". */
const _touch = (value: number | null | undefined): number | null =>
  typeof value === "number" && value > 0 ? value : null;
```

and inside the returned object, after `icon_url: g.icon,`:

```ts
    outcome_prices: parseOutcomePrices(g.outcomePrices),
    best_bid: _touch(g.bestBid),
    best_ask: _touch(g.bestAsk),
```

- [ ] **Step 5: Add the two helpers**

Append to `ui/src/lib/eventOutcomes.ts` (it already imports `Market`):

```ts
/** YES price per market id, taken straight from the list payload
 *  (`outcome_prices[0]`). Markets with no usable price are absent from the
 *  map — which is exactly what `sortMarketsByYesMid` treats as unknown and
 *  sorts last. */
export function yesPriceMap(
  markets: readonly Market[],
): ReadonlyMap<number, number> {
  const out = new Map<number, number>();
  for (const m of markets) {
    const price = m.outcome_prices[0];
    if (typeof price === "number" && Number.isFinite(price)) {
      out.set(m.market_id, price);
    }
  }
  return out;
}

/** Cents to BUY each side. YES costs its own best ask. NO is acquired through
 *  the YES book — the payload carries one bid/ask pair, describing YES — so it
 *  costs 1 − the YES best bid. */
export function buyChipCents(market: Market): {
  yes: number | null;
  no: number | null;
} {
  return {
    yes: market.best_ask !== null ? market.best_ask * 100 : null,
    no: market.best_bid !== null ? (1 - market.best_bid) * 100 : null,
  };
}
```

- [ ] **Step 6: Fix the two other Market fixtures**

`npm run typecheck` will fail in `ui/src/lib/eventChartSeries.test.ts` and `ui/src/lib/rotatingSeries.test.ts` — their local factories build a `Market` literal. Add to each factory's returned object:

```ts
    outcome_prices: [],
    best_bid: null,
    best_ask: null,
```

- [ ] **Step 7: Run the verify chain**

Run: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all tests pass, typecheck clean, lint 0 errors (3 pre-existing warnings), build succeeds.

- [ ] **Step 8: Commit**

```bash
git add ui/src/types/market.ts ui/src/api/markets.ts ui/src/api/markets.test.ts \
        ui/src/lib/eventOutcomes.ts ui/src/lib/eventOutcomes.test.ts \
        ui/src/lib/eventChartSeries.test.ts ui/src/lib/rotatingSeries.test.ts
git commit -m "feat(ui): carry outcome prices and the YES touch on Market

The server already derives prices for every market in one batch and ships
them as outcomePrices/bestBid/bestAsk; gammaToMarket was dropping them."
```

---

### Task 2: Home page reads prices from the payload

**Files:**
- Modify: `ui/src/components/MarketCard.tsx:6,32-34`
- Modify: `ui/src/components/MultiMarketEventCard.tsx:3,69`

**Interfaces:**
- Consumes: `Market.outcome_prices` and `yesPriceMap` from Task 1.
- Produces: nothing new; removes the last two home-page uses of `useOutcomeMid` / `useYesMidMap`.

- [ ] **Step 1: Rewrite MarketCard's price source**

In `ui/src/components/MarketCard.tsx`, delete the import line `import { useOutcomeMid } from "@/lib/useYesMid";` and replace these two lines:

```ts
  const { mid: yesMid } = useOutcomeMid(yesTokenId);
  const { data: spark } = usePricesHistory(yesTokenId);
  const yesPctLabel = formatProbabilityPct(yesMid);
```

with:

```ts
  const { data: spark } = usePricesHistory(yesTokenId);
  const yesPctLabel = formatProbabilityPct(market.outcome_prices[0] ?? null);
```

`yesTokenId` stays — `usePricesHistory` still needs it.

- [ ] **Step 2: Rewrite MultiMarketEventCard's map**

In `ui/src/components/MultiMarketEventCard.tsx`, replace the import `import { useYesMidMap } from "@/lib/useYesMid";` with `import { yesPriceMap } from "@/lib/eventOutcomes";` (that module is already imported for `sortMarketsByYesMid` — merge the named imports into the one statement rather than adding a second). Then replace:

```ts
  const midByMarket = useYesMidMap(markets);
```

with:

```ts
  const midByMarket = useMemo(() => yesPriceMap(markets), [markets]);
```

`useMemo` is already imported in this file.

- [ ] **Step 3: Run the verify chain**

Run: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all green. Typecheck is what proves no dangling `useOutcomeMid`/`useYesMidMap` reference remains in these two files.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/MarketCard.tsx ui/src/components/MultiMarketEventCard.tsx
git commit -m "perf(ui): home grid reads probabilities from the list payload

Was one GET /book per card (203 requests on a full home page); the same
number already arrives with the events list."
```

---

### Task 3: Event page reads prices from the payload

**Files:**
- Modify: `ui/src/pages/EventDetailPage.tsx:14,48`
- Modify: `ui/src/components/EventLeaderboardRow.tsx:1-3,58-68`

**Interfaces:**
- Consumes: `yesPriceMap`, `buyChipCents`, `Market.outcome_prices` from Task 1.
- Produces: nothing new; removes the last two uses of `useOutcomeMid` / `useYesMidMap` in the codebase, which Task 4 relies on.

- [ ] **Step 1: Rewrite EventDetailPage's map**

In `ui/src/pages/EventDetailPage.tsx`, delete `import { useYesMidMap } from "@/lib/useYesMid";` and add `yesPriceMap` to the existing named import from `@/lib/eventOutcomes` (which already brings in `sortMarketsByYesMid`). Then replace:

```ts
  const midByMarket = useYesMidMap(data?.markets ?? []);
```

with:

```ts
  const midByMarket = useMemo(() => yesPriceMap(data?.markets ?? []), [data]);
```

`useMemo` is already imported in this file.

- [ ] **Step 2: Rewrite EventLeaderboardRow's prices**

In `ui/src/components/EventLeaderboardRow.tsx`, delete these two imports:

```ts
import { bestAsk, deriveNoAsk } from "@/components/orders/orderMath";
import { useOutcomeMid } from "@/lib/useYesMid";
```

and add:

```ts
import { buyChipCents } from "@/lib/eventOutcomes";
```

Then replace this block (the `useOutcomeMid` calls through `yesPctLabel`):

```ts
  const yes = useOutcomeMid(yesTokenId);
  const no = useOutcomeMid(noTokenId);
  // The Yes/No chips are buy entry points, so show the price to BUY each
  // outcome — the order book's best ask — which agrees with the book to the
  // cent. The big % stays the mid (the market's implied probability).
  const yesAsk = yes.data ? bestAsk(yes.data.asks) : null;
  const noAsk = deriveNoAsk(no.data?.asks ?? [], yes.data?.bids ?? []);
  // Convert dollars to cents for display
  const yesCents = yesAsk !== null ? yesAsk * 100 : null;
  const noCents = noAsk !== null ? noAsk * 100 : null;
  const yesPctLabel = formatProbabilityPct(yes.mid);
```

with:

```ts
  // The Yes/No chips are buy entry points: YES costs its own best ask, and NO
  // is acquired through the YES book, so it costs 1 − the YES best bid. Both
  // come from the market payload — the row used to fetch two order books for
  // this, which is 52 of the event page's 58 book requests.
  const { yes: yesCents, no: noCents } = buyChipCents(market);
  const yesPctLabel = formatProbabilityPct(market.outcome_prices[0] ?? null);
```

`yesTokenId` / `noTokenId` remain if anything else in the file still reads them; if `npm run lint` reports either as unused, delete that declaration.

- [ ] **Step 3: Run the verify chain**

Run: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all green, 0 lint errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/EventDetailPage.tsx ui/src/components/EventLeaderboardRow.tsx
git commit -m "perf(ui): event page reads probabilities and chip prices from the payload

Each leaderboard row fetched two order books; with one bid/ask pair per
market on the wire, the NO chip is now derived as 1 - the YES bid."
```

---

### Task 4: Delete the dead hooks and keep detail pages fresh

**Files:**
- Delete: `ui/src/lib/useYesMid.ts`
- Delete: `ui/src/lib/useYesMidMap.test.ts`
- Modify: `ui/src/api/markets.ts:54-65` (`useMarket`)
- Modify: `ui/src/api/events.ts:105-114` (`useEvent`)

**Interfaces:**
- Consumes: Tasks 2 and 3 removed every consumer of `useYesMid.ts`.
- Produces: nothing.

- [ ] **Step 1: Confirm the module is unreferenced**

Run: `cd ui && grep -rn "useYesMid" src --include="*.ts" --include="*.tsx"`
Expected: only `src/lib/useYesMid.ts` and `src/lib/useYesMidMap.test.ts` match. If any other file matches, finish Task 2/3 there first — do not proceed.

- [ ] **Step 2: Delete both files**

```bash
rm ui/src/lib/useYesMid.ts ui/src/lib/useYesMidMap.test.ts
```

`computeMid` and `deriveNoCents` go with them; their only callers were that module's own tests. `deriveNoAsk`, `bestAsk` and `bestBid` live in `ui/src/components/orders/orderMath.ts` and **stay** — `OrderTicket` and `Orderbook` still use them and `orderMath.test.ts` still covers them.

- [ ] **Step 3: Add polling to the two detail-page queries**

The displayed percentage used to stay current because the book queries polled every 30 s. These two hooks do not poll, so without this the number would freeze at page load.

In `ui/src/api/markets.ts`, inside `useMarket`'s `useQuery({...})`, after `enabled: id !== undefined,`:

```ts
    // The probability now rides on the market payload rather than a 30s book
    // poll, so this query has to refresh it — one request instead of N.
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
```

In `ui/src/api/events.ts`, inside `useEvent`'s `useQuery({...})`, after `enabled: Boolean(slug),`:

```ts
    // Same reason as useMarket: the leaderboard's probabilities and chip
    // prices arrive with the event payload now.
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
```

- [ ] **Step 4: Run the verify chain**

Run: `cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all green. Vitest total drops by the deleted file's cases; nothing else changes.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/useYesMid.ts ui/src/lib/useYesMidMap.test.ts \
        ui/src/api/markets.ts ui/src/api/events.ts
git commit -m "refactor(ui): drop the per-market book hooks, poll the detail queries

useYesMid.ts has no consumers left. useMarket/useEvent take over the 30s
refresh the book queries used to provide."
```

---

### Task 5: Measure the result in a real browser

**Files:** none modified — this task produces evidence.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: before/after request counts for the commit trail.

- [ ] **Step 1: Serve the built UI against the production API**

> **Correction (post-ship review, 2026-07-29):** the command below does not
> work as written. Serving the UI on `localhost:5199` and pointing
> `VITE_API_BASE_URL` at `http://23.88.62.130:8000` fails outright — every
> request is blocked by CORS, because production's `AGENTPIT_CORS_ORIGINS`
> allowlist contains only `http://23.88.62.130` (`agentpit/config.py:116-117`
> / `agentpit/api/app.py:499-500`), not `http://localhost:5199`. The method
> that actually worked was a **temporary same-origin proxy**: add a `proxy`
> block to `ui/vite.config.ts` for the duration of the measurement (not
> committed) so the browser only ever talks to `localhost`, and Vite forwards
> `/api/*` server-side to production —
>
> ```ts
> server: {
>   port: 5199,
>   proxy: {
>     "/api": {
>       target: "http://23.88.62.130:8000",
>       changeOrigin: true,
>       rewrite: (path) => path.replace(/^\/api/, ""),
>     },
>   },
> },
> ```
>
> then point the app at the proxy instead of the raw host: `VITE_API_BASE_URL=/api`.
> Revert `vite.config.ts` after measuring — this is a throwaway measurement
> rig, not a feature.

```bash
cd ui && VITE_API_BASE_URL=/api npx vite --port 5199
```

Leave it running for the next steps. (The production API is public; no key is needed for `/events`, `/markets` or `/book`.)

- [ ] **Step 2: Measure the home page**

Open `http://localhost:5199/` in a browser (Playwright MCP or devtools), wait 8 s for the grid to settle, then run in the console:

```js
(() => {
  const es = performance.getEntriesByType("resource").filter(e => e.name.includes(":8000"));
  const by = {};
  for (const e of es) {
    const p = new URL(e.name).pathname;
    by[p] = (by[p] || 0) + 1;
  }
  return { total: es.length, byPath: by, lastMs: Math.round(Math.max(...es.map(e => e.responseEnd))) };
})()
```

Expected: `total` ~7 (was 210), **no `/book` entries at all** (was 203), `lastMs` under ~1500 (was 17451).

- [ ] **Step 3: Measure the event page**

Open `http://localhost:5199/events/presidential-election-winner-2028`, wait 7 s, run the same snippet.
Expected: `total` ~13 or fewer (was 70) — `/book` gone (was 58); the remaining `/prices-history` calls are sparklines and are explicitly out of scope.

- [ ] **Step 4: Sanity-check the numbers rendered**

On both pages confirm the percentages appear in the first paint (not after a delay) and are plausible (0-100%, not all "—" and not all 50%). Spot-check one market against `curl 'http://23.88.62.130:8000/markets?id=<id>'` — the displayed % must match `outcomePrices[0]` rounded.

- [ ] **Step 5: Stop the dev server and record the result**

Stop the vite process. Report the before/after table in the final summary: home 210 → N requests, event 70 → N requests, with the `lastMs` figures.

---

## Notes for the implementer

- The whole change is UI-only. If you find yourself editing anything under `agentpit/`, stop — the data you need is already on the wire.
- Do not "fix" `deriveNoAsk` or delete it: it is still exercised by `orderMath.test.ts` and belongs to the order-book module.
- **Correction (post-ship review, 2026-07-29):** the line that used to be here —
  "`formatProbabilityPct` already renders `null` as an em dash, so a market
  with no price shows '—' exactly as it does today" — was wrong about the
  server contract. `agentpit/polymarket/gamma.py:40-47` and
  `agentpit/polymarket/pricing.py:69-75` guarantee `outcomePrices` is always
  populated, falling back all the way to `0.5` per outcome when there is no
  book and no trade. `outcome_prices[0]` is therefore never absent from a
  live server today, so the dimmed "—" path is not reachable in production —
  a market with truly no price now renders a confident, undimmed "50", which
  is a real behavior change from the pre-migration client (whose own book
  fetch could genuinely come back empty). `formatProbabilityPct(null)` and
  the dimmed-state checks in `MarketCard` / `EventLeaderboardRow` are kept
  because they are still correct for the `Market` type's declared contract
  (`outcome_prices` can be `[]`), not because this server will exercise them.
