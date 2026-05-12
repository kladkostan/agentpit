# Order Placement UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Polymarket-style order ticket and live orderbook to `MarketDetailPage` so authenticated users can place limit and market orders for YES/NO outcome tokens.

**Architecture:** Frontend-only. New `OrderTicket` and `Orderbook` components in `ui/src/components/orders/`. Market orders are client-side: place a slippage-capped GTC limit, then DELETE any unfilled remainder. No backend changes.

**Tech Stack:** React 18, TypeScript (strict), Vite, Tailwind, Radix primitives, TanStack Query (already in deps). New deps: `vitest` (unit tests), `sonner` (toasts).

**Reference spec:** [docs/superpowers/specs/2026-05-12-order-placement-ui-design.md](../specs/2026-05-12-order-placement-ui-design.md)

---

## File Structure

```
ui/
├── package.json                                       [modify] add deps + scripts
├── vitest.config.ts                                   [new]    Vitest config (reuses vite resolve.alias)
└── src/
    ├── App.tsx                                        [modify] mount <Toaster />
    ├── types/
    │   └── order.ts                                   [new]    PlaceOrderRequest, OrderResponse, OrderbookEntry, OrderbookResponse, MarketOrderResult
    ├── api/
    │   └── orders.ts                                  [new]    placeOrder, cancelOrder, useOrderbook, placeMarketOrder
    ├── components/
    │   └── orders/                                    [new]
    │       ├── orderMath.ts                           [new]    pure conversions: shares↔dollars, slippage caps
    │       ├── orderMath.test.ts                      [new]    Vitest unit tests
    │       ├── OutcomeChips.tsx                       [new]    YES/NO toggle
    │       ├── Orderbook.tsx                          [new]    bids/asks ladder for selected outcome
    │       └── OrderTicket.tsx                        [new]    Buy/Sell × Limit/Market form + submit
    └── pages/
        └── MarketDetailPage.tsx                       [modify] widen to max-w-5xl, two-col grid, mount the three new components
```

**Wire formats (recap from backend):**
- Wire `size` is integer micro-shares (display shares × 10⁶). 100 shares = `100_000_000`.
- Wire `price` is decimal probability `0 < p < 1` (e.g. `0.65`).
- Orderbook `PRICE` is integer micro-USDC (`price × 10⁶`). `0.65` → `650_000`.
- Orderbook `REMAINING_AMOUNT` is in outcome-token units regardless of side (so we can compare BUY/SELL directly).

**Constants in `orderMath.ts`:**
- `SLIPPAGE_CAP = 0.02` (2¢)
- `MIN_PROB = 0.01`, `MAX_PROB = 0.99` (clamp boundaries)
- `SHARES_SCALE = 1_000_000` (wire factor)

---

## Task 1: Set up Vitest

**Files:**
- Modify: `ui/package.json`
- Create: `ui/vitest.config.ts`
- Create: `ui/src/__smoke__.test.ts` (temporary, deleted in this task)

- [ ] **Step 1: Add deps and scripts**

Run from `ui/`:

```bash
cd ui
yarn add -D vitest@^2 jsdom @testing-library/jest-dom
```

Then open `ui/package.json` and add these two lines under `"scripts"` (after `"format"`):

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 2: Create `ui/vitest.config.ts`**

```ts
import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "node",
      include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    },
  }),
);
```

(Uses `node` env — the only tests in this plan are pure-function math. If component tests are added later, switch to `jsdom`.)

- [ ] **Step 3: Create a smoke test to verify the runner works**

`ui/src/__smoke__.test.ts`:

```ts
import { describe, expect, it } from "vitest";

describe("vitest setup", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd ui && yarn test
```

Expected: 1 passed (1).

- [ ] **Step 5: Delete the smoke test and commit**

```bash
rm ui/src/__smoke__.test.ts
git add ui/package.json ui/yarn.lock ui/vitest.config.ts
git commit -m "$(cat <<'EOF'
chore(ui): set up Vitest for pure-function unit tests

Adds vitest config that inherits the vite resolve.alias so '@/' imports
work in tests too. Node environment; tests live next to source as
*.test.ts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Order type definitions

**Files:**
- Create: `ui/src/types/order.ts`

- [ ] **Step 1: Write the file**

```ts
export type OrderSide = "BUY" | "SELL";
export type OrderType = "GTC" | "FOK" | "FAK" | "GTD";

export interface PlaceOrderRequest {
  market_id: number;
  outcome: string;       // label, e.g. "Yes" / "No"
  side: OrderSide;
  price: number;         // 0 < price < 1
  size: number;          // integer micro-shares (display × 1e6)
  order_type?: OrderType;
  expiration?: number;
}

export interface OrderResponse {
  success: boolean;
  orderID: string;
  status: string;        // "live" | "matched" | "cancelled" | "failed"
  filledSize: string;    // micro-shares as decimal string
  remainingSize: string; // micro-shares as decimal string
  avgPrice?: string | null;
  errorMsg?: string | null;
  txHash?: string | null;
}

export interface OrderbookEntry {
  ORDER_ID: string;
  SIDE: OrderSide;
  PRICE: number;             // integer micro-USDC
  REMAINING_AMOUNT: number;  // integer micro-shares
  MAKER: string;
  CREATED_AT: number;
}

export interface OrderbookResponse {
  market_id: number;
  outcome: string;
  bids: OrderbookEntry[];
  asks: OrderbookEntry[];
}

export interface MarketOrderResult {
  filledShares: number;       // display shares (already divided by 1e6)
  remainingShares: number;
  avgPrice: number | null;
  txHash: string | null;
  cancelledRemainder: boolean;
  cancelError?: string;
  orderID: string;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/types/order.ts
git commit -m "$(cat <<'EOF'
feat(ui): add order/orderbook type definitions

Mirrors the wire formats from agentpit/datastructures/place_order_request.py
and the orderbook shape returned by GET /orderbook/{market_id}/{outcome}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: orderMath — shares ↔ dollars conversions

**Files:**
- Create: `ui/src/components/orders/orderMath.ts`
- Create: `ui/src/components/orders/orderMath.test.ts`

TDD. We build constants + the two simplest conversions first.

- [ ] **Step 1: Write failing test**

`ui/src/components/orders/orderMath.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { dollarsFromShares, sharesFromDollars } from "./orderMath";

describe("sharesFromDollars", () => {
  it("converts $50 at 0.65 to 76.923 shares (rounded down)", () => {
    expect(sharesFromDollars(50, 0.65)).toBeCloseTo(76.923076, 5);
  });

  it("returns 0 when price is 0", () => {
    expect(sharesFromDollars(50, 0)).toBe(0);
  });

  it("returns 0 when amount is 0", () => {
    expect(sharesFromDollars(0, 0.65)).toBe(0);
  });
});

describe("dollarsFromShares", () => {
  it("converts 100 shares at 0.65 to $65", () => {
    expect(dollarsFromShares(100, 0.65)).toBeCloseTo(65, 5);
  });

  it("returns 0 when shares is 0", () => {
    expect(dollarsFromShares(0, 0.65)).toBe(0);
  });

  it("round-trips: dollarsFromShares(sharesFromDollars(amt, p), p) ≈ amt", () => {
    expect(dollarsFromShares(sharesFromDollars(50, 0.65), 0.65)).toBeCloseTo(50, 4);
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd ui && yarn test
```

Expected: tests fail with "Failed to load url './orderMath'" or similar — module doesn't exist yet.

- [ ] **Step 3: Implement minimal `orderMath.ts`**

`ui/src/components/orders/orderMath.ts`:

```ts
export const SLIPPAGE_CAP = 0.02;
export const MIN_PROB = 0.01;
export const MAX_PROB = 0.99;
export const SHARES_SCALE = 1_000_000;

/** Display shares from dollar amount at a price. Returns 0 for invalid inputs. */
export function sharesFromDollars(amount: number, price: number): number {
  if (amount <= 0 || price <= 0) return 0;
  return amount / price;
}

/** Dollar cost of N display shares at a price. */
export function dollarsFromShares(shares: number, price: number): number {
  if (shares <= 0 || price <= 0) return 0;
  return shares * price;
}
```

- [ ] **Step 4: Run, expect pass**

```bash
cd ui && yarn test
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/orders/orderMath.ts ui/src/components/orders/orderMath.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): add orderMath shares↔dollars conversions

Pure functions, no React. First module with Vitest unit tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: orderMath — `computeMarketBuy`

Derives the slippage-capped `(price, size)` for a Market BUY given the orderbook asks and a dollar budget.

**Files:**
- Modify: `ui/src/components/orders/orderMath.ts`
- Modify: `ui/src/components/orders/orderMath.test.ts`

- [ ] **Step 1: Add failing tests**

Append to `orderMath.test.ts`:

```ts
import { computeMarketBuy } from "./orderMath";
import type { OrderbookEntry } from "@/types/order";

const ask = (
  price: number,
  remainingShares: number,
): OrderbookEntry => ({
  ORDER_ID: `ask-${price}-${remainingShares}`,
  SIDE: "SELL",
  PRICE: Math.round(price * 1_000_000),
  REMAINING_AMOUNT: remainingShares * 1_000_000,
  MAKER: "0x0",
  CREATED_AT: 0,
});

describe("computeMarketBuy", () => {
  it("returns null for an empty book", () => {
    expect(computeMarketBuy([], 50)).toBeNull();
  });

  it("caps at best_ask + SLIPPAGE_CAP", () => {
    const result = computeMarketBuy([ask(0.65, 100)], 50);
    expect(result).not.toBeNull();
    expect(result!.priceCap).toBeCloseTo(0.67, 5);
    expect(result!.sizeWire).toBe(Math.floor((50 * 1_000_000) / 0.67));
  });

  it("clamps price cap at MAX_PROB (0.99)", () => {
    const result = computeMarketBuy([ask(0.98, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.99, 5);
  });

  it("returns null for non-positive amount", () => {
    expect(computeMarketBuy([ask(0.65, 100)], 0)).toBeNull();
    expect(computeMarketBuy([ask(0.65, 100)], -1)).toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd ui && yarn test
```

Expected: `computeMarketBuy is not exported`.

- [ ] **Step 3: Implement**

Append to `orderMath.ts`:

```ts
import type { OrderbookEntry } from "@/types/order";

export interface MarketBuyComputation {
  priceCap: number;     // probability used for the wire price
  sizeWire: number;     // integer micro-shares for the wire size
  bestAsk: number;      // top-of-book ask for preview display
}

/**
 * Given asks (sorted or unsorted) and a dollar budget, derive the
 * (price, size) for a GTC limit that fills against the book up to the
 * slippage cap. The remainder, if any, can be DELETE'd by the caller.
 */
export function computeMarketBuy(
  asks: OrderbookEntry[],
  dollarAmount: number,
): MarketBuyComputation | null {
  if (asks.length === 0 || dollarAmount <= 0) return null;
  const best = Math.min(...asks.map((a) => a.PRICE)) / 1_000_000;
  const priceCap = Math.min(best + SLIPPAGE_CAP, MAX_PROB);
  const sizeWire = Math.floor((dollarAmount * SHARES_SCALE) / priceCap);
  if (sizeWire <= 0) return null;
  return { priceCap, sizeWire, bestAsk: best };
}
```

- [ ] **Step 4: Run, expect pass**

```bash
cd ui && yarn test
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/orders/orderMath.ts ui/src/components/orders/orderMath.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): add computeMarketBuy for slippage-capped market BUY

Returns null on empty book or zero budget. Caps at MAX_PROB (0.99).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: orderMath — `computeMarketSell`

**Files:**
- Modify: `ui/src/components/orders/orderMath.ts`
- Modify: `ui/src/components/orders/orderMath.test.ts`

- [ ] **Step 1: Add failing tests**

```ts
import { computeMarketSell } from "./orderMath";

const bid = (
  price: number,
  remainingShares: number,
): OrderbookEntry => ({
  ORDER_ID: `bid-${price}-${remainingShares}`,
  SIDE: "BUY",
  PRICE: Math.round(price * 1_000_000),
  REMAINING_AMOUNT: remainingShares * 1_000_000,
  MAKER: "0x0",
  CREATED_AT: 0,
});

describe("computeMarketSell", () => {
  it("returns null for an empty book", () => {
    expect(computeMarketSell([], 100)).toBeNull();
  });

  it("caps at best_bid - SLIPPAGE_CAP", () => {
    const result = computeMarketSell([bid(0.65, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.63, 5);
    expect(result!.sizeWire).toBe(50 * 1_000_000);
  });

  it("clamps price cap at MIN_PROB (0.01)", () => {
    const result = computeMarketSell([bid(0.02, 100)], 50);
    expect(result!.priceCap).toBeCloseTo(0.01, 5);
  });

  it("returns null for non-positive shares", () => {
    expect(computeMarketSell([bid(0.65, 100)], 0)).toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd ui && yarn test
```

- [ ] **Step 3: Implement**

Append to `orderMath.ts`:

```ts
export interface MarketSellComputation {
  priceCap: number;
  sizeWire: number;
  bestBid: number;
}

export function computeMarketSell(
  bids: OrderbookEntry[],
  shares: number,
): MarketSellComputation | null {
  if (bids.length === 0 || shares <= 0) return null;
  const best = Math.max(...bids.map((b) => b.PRICE)) / 1_000_000;
  const priceCap = Math.max(best - SLIPPAGE_CAP, MIN_PROB);
  const sizeWire = Math.floor(shares * SHARES_SCALE);
  if (sizeWire <= 0) return null;
  return { priceCap, sizeWire, bestBid: best };
}
```

- [ ] **Step 4: Run, expect pass**

```bash
cd ui && yarn test
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/orders/orderMath.ts ui/src/components/orders/orderMath.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): add computeMarketSell for slippage-capped market SELL

Symmetric to computeMarketBuy. Clamps at MIN_PROB (0.01).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: API client — `placeOrder` + `cancelOrder`

**Files:**
- Create: `ui/src/api/orders.ts`

- [ ] **Step 1: Write the file**

```ts
import { apiFetch } from "@/api/client";
import type { OrderResponse, PlaceOrderRequest } from "@/types/order";

export async function placeOrder(
  req: PlaceOrderRequest,
): Promise<OrderResponse> {
  return apiFetch<OrderResponse>("/orders", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function cancelOrder(orderId: string): Promise<void> {
  await apiFetch<{ order_id: string; status: string }>(
    `/orders/${encodeURIComponent(orderId)}`,
    { method: "DELETE" },
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/api/orders.ts
git commit -m "$(cat <<'EOF'
feat(ui): add placeOrder and cancelOrder API client functions

Thin wrappers over apiFetch — auth header is added automatically by
the existing token getter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: API client — `useOrderbook` hook with polling

**Files:**
- Modify: `ui/src/api/orders.ts`

- [ ] **Step 1: Add `getOrderbook` and `useOrderbook`**

Append to `ui/src/api/orders.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import type { OrderbookResponse } from "@/types/order";

export async function getOrderbook(
  marketId: number,
  outcome: string,
): Promise<OrderbookResponse> {
  return apiFetch<OrderbookResponse>(
    `/orderbook/${marketId}/${encodeURIComponent(outcome)}`,
  );
}

export function useOrderbook(
  marketId: number | undefined,
  outcome: string | undefined,
) {
  return useQuery({
    queryKey: ["orderbook", marketId, outcome],
    queryFn: () => {
      if (marketId === undefined || !outcome) {
        throw new Error("marketId and outcome are required");
      }
      return getOrderbook(marketId, outcome);
    },
    enabled: marketId !== undefined && Boolean(outcome),
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
  });
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/api/orders.ts
git commit -m "$(cat <<'EOF'
feat(ui): add useOrderbook React Query hook with 3s polling

Pauses when the tab is backgrounded (refetchIntervalInBackground: false).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: API client — `placeMarketOrder` two-step

**Files:**
- Modify: `ui/src/api/orders.ts`

- [ ] **Step 1: Add the function**

Append to `ui/src/api/orders.ts`:

```ts
import { ApiError } from "@/api/client";
import { SHARES_SCALE, computeMarketBuy, computeMarketSell } from "@/components/orders/orderMath";
import type { MarketOrderResult, OrderSide } from "@/types/order";

export interface PlaceMarketOrderArgs {
  marketId: number;
  outcome: string;
  side: OrderSide;
  /** For BUY: dollar amount. For SELL: display-share count. */
  amount: number;
  book: OrderbookResponse;
}

export async function placeMarketOrder(
  args: PlaceMarketOrderArgs,
): Promise<MarketOrderResult> {
  const computation =
    args.side === "BUY"
      ? computeMarketBuy(args.book.asks, args.amount)
      : computeMarketSell(args.book.bids, args.amount);

  if (computation === null) {
    throw new Error(
      args.side === "BUY"
        ? "No asks available — use a limit order"
        : "No bids available — use a limit order",
    );
  }

  const response = await placeOrder({
    market_id: args.marketId,
    outcome: args.outcome,
    side: args.side,
    price: computation.priceCap,
    size: computation.sizeWire,
    order_type: "GTC",
  });

  let cancelledRemainder = false;
  let cancelError: string | undefined;
  if (
    response.success &&
    Number(response.remainingSize) > 0 &&
    response.status === "live"
  ) {
    try {
      await cancelOrder(response.orderID);
      cancelledRemainder = true;
    } catch (err) {
      cancelError = err instanceof ApiError ? err.message : String(err);
    }
  }

  const filledShares = Number(response.filledSize) / SHARES_SCALE;
  const remainingShares = Number(response.remainingSize) / SHARES_SCALE;
  const result: MarketOrderResult = {
    filledShares,
    remainingShares,
    avgPrice: response.avgPrice ? Number(response.avgPrice) : null,
    txHash: response.txHash ?? null,
    cancelledRemainder,
    orderID: response.orderID,
  };
  if (cancelError !== undefined) {
    result.cancelError = cancelError;
  }
  return result;
}
```

Note: `exactOptionalPropertyTypes: true` is on in `tsconfig.app.json`, so `cancelError` is only assigned when defined.

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/api/orders.ts
git commit -m "$(cat <<'EOF'
feat(ui): add placeMarketOrder two-step (place + maybe-cancel)

Derives slippage-capped (price, size) from the cached orderbook, places
a GTC limit, then best-effort DELETEs any unfilled remainder. Cancel
failures are surfaced via the result, not thrown.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Add `sonner` toaster

**Files:**
- Modify: `ui/package.json`
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Install sonner**

```bash
cd ui && yarn add sonner
```

- [ ] **Step 2: Mount the Toaster in App**

Edit `ui/src/App.tsx`:

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { TopNav } from "@/components/TopNav";
import { MarketsPage } from "@/pages/MarketsPage";
import { MarketDetailPage } from "@/pages/MarketDetailPage";

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopNav />
      <main className="container py-8">
        <Routes>
          <Route path="/" element={<MarketsPage />} />
          <Route path="/markets/:id" element={<MarketDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 4: Commit**

```bash
git add ui/package.json ui/yarn.lock ui/src/App.tsx
git commit -m "$(cat <<'EOF'
feat(ui): mount sonner Toaster at app root

Used by the order ticket to surface place/cancel results.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `OutcomeChips` component

**Files:**
- Create: `ui/src/components/orders/OutcomeChips.tsx`

- [ ] **Step 1: Write the component**

```tsx
import type { Erc1155Token } from "@/types/market";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface OutcomeChipsProps {
  tokens: Erc1155Token[];
  selected: string;
  onSelect: (label: string) => void;
}

export function OutcomeChips({ tokens, selected, onSelect }: OutcomeChipsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {tokens.map(([tokenId, label]) => {
        const isActive = label === selected;
        return (
          <Button
            key={tokenId}
            type="button"
            variant={isActive ? "default" : "outline"}
            size="sm"
            onClick={() => onSelect(label)}
            className={cn("min-w-[5rem]", isActive && "shadow")}
          >
            {label}
          </Button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/orders/OutcomeChips.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add OutcomeChips selector for YES/NO toggle

Controlled component; the active label is the source of truth for both
the Orderbook and OrderTicket panels.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `Orderbook` component

**Files:**
- Create: `ui/src/components/orders/Orderbook.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { useOrderbook } from "@/api/orders";
import { Skeleton } from "@/components/ui/skeleton";
import type { OrderbookEntry } from "@/types/order";
import { SHARES_SCALE } from "@/components/orders/orderMath";

interface OrderbookProps {
  marketId: number;
  outcome: string;
}

const DEPTH = 8;

const formatPrice = (microUsdc: number): string =>
  (microUsdc / 1_000_000).toFixed(2);

const formatSize = (microShares: number): string =>
  (microShares / SHARES_SCALE).toFixed(2);

const aggregateByPrice = (entries: OrderbookEntry[]): OrderbookEntry[] => {
  const acc = new Map<number, OrderbookEntry>();
  for (const e of entries) {
    const existing = acc.get(e.PRICE);
    if (existing) {
      existing.REMAINING_AMOUNT += e.REMAINING_AMOUNT;
    } else {
      acc.set(e.PRICE, { ...e });
    }
  }
  return [...acc.values()];
};

export function Orderbook({ marketId, outcome }: OrderbookProps) {
  const { data, isLoading, error, isStale } = useOrderbook(marketId, outcome);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="text-sm text-muted-foreground">
        Orderbook unavailable — retrying.
      </p>
    );
  }

  const asks = aggregateByPrice(data.asks)
    .sort((a, b) => a.PRICE - b.PRICE)
    .slice(0, DEPTH)
    .reverse(); // display highest ask at top
  const bids = aggregateByPrice(data.bids)
    .sort((a, b) => b.PRICE - a.PRICE)
    .slice(0, DEPTH);

  return (
    <section className="space-y-2">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Orderbook — {outcome}
        </h2>
        {isStale ? (
          <span className="text-xs text-muted-foreground">stale</span>
        ) : null}
      </header>

      <div className="rounded-lg border">
        <div className="grid grid-cols-3 border-b bg-muted/30 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span>Price</span>
          <span className="text-right">Size</span>
          <span className="text-right">Total</span>
        </div>

        {asks.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">no asks</p>
        ) : (
          asks.map((entry) => (
            <Row key={entry.ORDER_ID} entry={entry} kind="ask" />
          ))
        )}

        <div className="border-t border-dashed" />

        {bids.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">no bids</p>
        ) : (
          bids.map((entry) => (
            <Row key={entry.ORDER_ID} entry={entry} kind="bid" />
          ))
        )}
      </div>
    </section>
  );
}

function Row({
  entry,
  kind,
}: {
  entry: OrderbookEntry;
  kind: "ask" | "bid";
}) {
  const price = formatPrice(entry.PRICE);
  const size = formatSize(entry.REMAINING_AMOUNT);
  const total = (
    (entry.PRICE / 1_000_000) *
    (entry.REMAINING_AMOUNT / SHARES_SCALE)
  ).toFixed(2);
  return (
    <div className="grid grid-cols-3 px-3 py-1.5 text-sm tabular-nums">
      <span
        className={
          kind === "ask"
            ? "text-rose-600 dark:text-rose-400"
            : "text-emerald-600 dark:text-emerald-400"
        }
      >
        ${price}
      </span>
      <span className="text-right">{size}</span>
      <span className="text-right text-muted-foreground">${total}</span>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/orders/Orderbook.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add Orderbook component with bids/asks ladder

Aggregates entries by price level, shows top 8 each side, polls via
useOrderbook. Empty / stale states handled inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `OrderTicket` scaffolding (tabs + inputs + preview, no submit)

**Files:**
- Create: `ui/src/components/orders/OrderTicket.tsx`

Build the form structure first. Submit logic comes in Tasks 13 and 14.

- [ ] **Step 1: Write the component**

```tsx
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useOrderbook } from "@/api/orders";
import {
  MAX_PROB,
  MIN_PROB,
  SLIPPAGE_CAP,
  computeMarketBuy,
  computeMarketSell,
  dollarsFromShares,
  sharesFromDollars,
} from "@/components/orders/orderMath";
import type { OrderSide } from "@/types/order";

type Mode = "Limit" | "Market";

interface OrderTicketProps {
  marketId: number;
  outcome: string;
  isTradingDisabled: boolean;
  disabledReason?: string;
}

export function OrderTicket({
  marketId,
  outcome,
  isTradingDisabled,
  disabledReason,
}: OrderTicketProps) {
  const [side, setSide] = useState<OrderSide>("BUY");
  const [mode, setMode] = useState<Mode>("Limit");
  const [limitPrice, setLimitPrice] = useState<string>("0.50");
  const [limitShares, setLimitShares] = useState<string>("");
  const [marketAmount, setMarketAmount] = useState<string>("");

  const { data: book } = useOrderbook(marketId, outcome);
  const bestAsk = book && book.asks.length > 0
    ? Math.min(...book.asks.map((a) => a.PRICE)) / 1_000_000
    : null;
  const bestBid = book && book.bids.length > 0
    ? Math.max(...book.bids.map((b) => b.PRICE)) / 1_000_000
    : null;

  const preview = useMemo(() => {
    if (mode === "Limit") {
      const price = Number(limitPrice);
      const shares = Number(limitShares);
      if (!Number.isFinite(price) || !Number.isFinite(shares)) return null;
      if (price <= 0 || price >= 1 || shares <= 0) return null;
      return {
        priceLabel: `$${price.toFixed(2)}`,
        sharesLabel: shares.toFixed(2),
        totalLabel: `$${dollarsFromShares(shares, price).toFixed(2)}`,
        capWarning: null as string | null,
      };
    }
    const amount = Number(side === "BUY" ? marketAmount : limitShares);
    if (!book) return null;
    if (!Number.isFinite(amount) || amount <= 0) return null;
    if (side === "BUY") {
      const comp = computeMarketBuy(book.asks, amount);
      if (!comp) return null;
      const shares = sharesFromDollars(amount, comp.priceCap);
      return {
        priceLabel: `≤ $${comp.priceCap.toFixed(2)}`,
        sharesLabel: `~${shares.toFixed(2)}`,
        totalLabel: `$${amount.toFixed(2)}`,
        capWarning:
          comp.priceCap >= MAX_PROB
            ? `Cap clamped to ${MAX_PROB.toFixed(2)}`
            : null,
      };
    }
    const comp = computeMarketSell(book.bids, amount);
    if (!comp) return null;
    const total = dollarsFromShares(amount, comp.priceCap);
    return {
      priceLabel: `≥ $${comp.priceCap.toFixed(2)}`,
      sharesLabel: amount.toFixed(2),
      totalLabel: `~$${total.toFixed(2)}`,
      capWarning:
        comp.priceCap <= MIN_PROB
          ? `Cap clamped to ${MIN_PROB.toFixed(2)}`
          : null,
    };
  }, [mode, side, limitPrice, limitShares, marketAmount, book]);

  const canSubmit =
    !isTradingDisabled &&
    preview !== null &&
    (mode === "Limit" ||
      (side === "BUY" ? bestAsk !== null : bestBid !== null));

  return (
    <section className="space-y-4 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Order ticket</h2>
        <span className="text-xs text-muted-foreground">{outcome}</span>
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["BUY", "SELL"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSide(s)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              side === s
                ? s === "BUY"
                  ? "bg-emerald-600 text-white shadow"
                  : "bg-rose-600 text-white shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "BUY" ? "Buy" : "Sell"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["Limit", "Market"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              mode === m
                ? "bg-background shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "Limit" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="limit-price">Limit price ($)</Label>
            <Input
              id="limit-price"
              type="number"
              inputMode="decimal"
              min="0.01"
              max="0.99"
              step="0.01"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="limit-shares">Shares</Label>
            <Input
              id="limit-shares"
              type="number"
              inputMode="decimal"
              min="0"
              step="1"
              value={limitShares}
              onChange={(e) => setLimitShares(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
        </div>
      ) : side === "BUY" ? (
        <div className="space-y-1.5">
          <Label htmlFor="market-amount">Amount ($)</Label>
          <Input
            id="market-amount"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={marketAmount}
            onChange={(e) => setMarketAmount(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} above best ask
            {bestAsk !== null ? ` ($${bestAsk.toFixed(2)})` : ""}
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="market-shares">Shares to sell</Label>
          <Input
            id="market-shares"
            type="number"
            inputMode="decimal"
            min="0"
            step="1"
            value={limitShares}
            onChange={(e) => setLimitShares(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} below best bid
            {bestBid !== null ? ` ($${bestBid.toFixed(2)})` : ""}
          </p>
        </div>
      )}

      <dl className="space-y-1 rounded-md border bg-muted/30 p-3 text-xs">
        <Row label="Price" value={preview?.priceLabel ?? "—"} />
        <Row label="Shares" value={preview?.sharesLabel ?? "—"} />
        <Row label="Total" value={preview?.totalLabel ?? "—"} />
        {preview?.capWarning ? (
          <Row label="" value={preview.capWarning} muted />
        ) : null}
      </dl>

      <Button
        type="button"
        size="lg"
        disabled={!canSubmit}
        className="w-full"
        onClick={() => {
          /* wired in Task 13 / 14 */
        }}
      >
        {isTradingDisabled
          ? (disabledReason ?? "Trading disabled")
          : `${side === "BUY" ? "Buy" : "Sell"} ${outcome}`}
      </Button>
    </section>
  );
}

function Row({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "tabular-nums",
          muted ? "text-muted-foreground" : "font-medium",
        )}
      >
        {value}
      </dd>
    </div>
  );
}
```

Note: this task intentionally re-uses `limitShares` for the Market-SELL input as well. Both are "shares" semantically.

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/orders/OrderTicket.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add OrderTicket scaffolding (tabs, inputs, live preview)

Submit button is wired in the next two tasks. Inputs and preview are
all driven from local state + the cached orderbook.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Wire `OrderTicket` Limit submit + integrate into `MarketDetailPage`

This task wires the Limit submit AND mounts everything on the page so we can manually verify it works end-to-end.

**Files:**
- Modify: `ui/src/components/orders/OrderTicket.tsx`
- Modify: `ui/src/pages/MarketDetailPage.tsx`

- [ ] **Step 1: Add `onSubmit` Limit handler in OrderTicket**

Replace the `OrderTicket` component's imports and add `useMutation`, `useQueryClient`, `useRequireAuth`, `placeOrder`, `toast`. Replace the `onClick` handler. Here is the full file after the edit:

```tsx
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { placeOrder, useOrderbook } from "@/api/orders";
import { useRequireAuth } from "@/auth/useRequireAuth";
import {
  MAX_PROB,
  MIN_PROB,
  SHARES_SCALE,
  SLIPPAGE_CAP,
  computeMarketBuy,
  computeMarketSell,
  dollarsFromShares,
  sharesFromDollars,
} from "@/components/orders/orderMath";
import type { OrderSide } from "@/types/order";
import { ApiError } from "@/api/client";

type Mode = "Limit" | "Market";

interface OrderTicketProps {
  marketId: number;
  outcome: string;
  isTradingDisabled: boolean;
  disabledReason?: string;
}

export function OrderTicket({
  marketId,
  outcome,
  isTradingDisabled,
  disabledReason,
}: OrderTicketProps) {
  const [side, setSide] = useState<OrderSide>("BUY");
  const [mode, setMode] = useState<Mode>("Limit");
  const [limitPrice, setLimitPrice] = useState<string>("0.50");
  const [limitShares, setLimitShares] = useState<string>("");
  const [marketAmount, setMarketAmount] = useState<string>("");

  const requireAuth = useRequireAuth();
  const queryClient = useQueryClient();
  const { data: book } = useOrderbook(marketId, outcome);

  const bestAsk =
    book && book.asks.length > 0
      ? Math.min(...book.asks.map((a) => a.PRICE)) / 1_000_000
      : null;
  const bestBid =
    book && book.bids.length > 0
      ? Math.max(...book.bids.map((b) => b.PRICE)) / 1_000_000
      : null;

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ["orderbook", marketId, outcome],
    });
    void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  };

  const limitMutation = useMutation({
    mutationFn: async () => {
      const price = Number(limitPrice);
      const shares = Number(limitShares);
      return placeOrder({
        market_id: marketId,
        outcome,
        side,
        price,
        size: Math.floor(shares * SHARES_SCALE),
        order_type: "GTC",
      });
    },
    onSuccess: (res) => {
      if (!res.success) {
        toast.error(`Order failed: ${res.errorMsg ?? "unknown"}`);
        return;
      }
      const filled = Number(res.filledSize) / SHARES_SCALE;
      const remaining = Number(res.remainingSize) / SHARES_SCALE;
      toast.success(
        remaining > 0
          ? `Order placed: ${filled.toFixed(2)} filled, ${remaining.toFixed(
              2,
            )} resting`
          : `Order filled: ${filled.toFixed(2)} shares`,
      );
      setLimitShares("");
      invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : String(err));
    },
  });

  const preview = useMemo(() => {
    /* unchanged from Task 12 — preserved exactly */
    if (mode === "Limit") {
      const price = Number(limitPrice);
      const shares = Number(limitShares);
      if (!Number.isFinite(price) || !Number.isFinite(shares)) return null;
      if (price <= 0 || price >= 1 || shares <= 0) return null;
      return {
        priceLabel: `$${price.toFixed(2)}`,
        sharesLabel: shares.toFixed(2),
        totalLabel: `$${dollarsFromShares(shares, price).toFixed(2)}`,
        capWarning: null as string | null,
      };
    }
    const amount = Number(side === "BUY" ? marketAmount : limitShares);
    if (!book) return null;
    if (!Number.isFinite(amount) || amount <= 0) return null;
    if (side === "BUY") {
      const comp = computeMarketBuy(book.asks, amount);
      if (!comp) return null;
      const shares = sharesFromDollars(amount, comp.priceCap);
      return {
        priceLabel: `≤ $${comp.priceCap.toFixed(2)}`,
        sharesLabel: `~${shares.toFixed(2)}`,
        totalLabel: `$${amount.toFixed(2)}`,
        capWarning:
          comp.priceCap >= MAX_PROB
            ? `Cap clamped to ${MAX_PROB.toFixed(2)}`
            : null,
      };
    }
    const comp = computeMarketSell(book.bids, amount);
    if (!comp) return null;
    const total = dollarsFromShares(amount, comp.priceCap);
    return {
      priceLabel: `≥ $${comp.priceCap.toFixed(2)}`,
      sharesLabel: amount.toFixed(2),
      totalLabel: `~$${total.toFixed(2)}`,
      capWarning:
        comp.priceCap <= MIN_PROB
          ? `Cap clamped to ${MIN_PROB.toFixed(2)}`
          : null,
    };
  }, [mode, side, limitPrice, limitShares, marketAmount, book]);

  const canSubmit =
    !isTradingDisabled &&
    preview !== null &&
    !limitMutation.isPending &&
    (mode === "Limit" ||
      (side === "BUY" ? bestAsk !== null : bestBid !== null));

  const onSubmit = requireAuth(() => {
    if (mode === "Limit") {
      limitMutation.mutate();
    } else {
      // Wired in Task 14.
      toast.message("Market orders coming next");
    }
  });

  return (
    <section className="space-y-4 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Order ticket</h2>
        <span className="text-xs text-muted-foreground">{outcome}</span>
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["BUY", "SELL"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSide(s)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              side === s
                ? s === "BUY"
                  ? "bg-emerald-600 text-white shadow"
                  : "bg-rose-600 text-white shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s === "BUY" ? "Buy" : "Sell"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-1 rounded-md bg-muted p-1">
        {(["Limit", "Market"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "rounded-sm py-1.5 text-sm font-medium transition",
              mode === m
                ? "bg-background shadow"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "Limit" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="limit-price">Limit price ($)</Label>
            <Input
              id="limit-price"
              type="number"
              inputMode="decimal"
              min="0.01"
              max="0.99"
              step="0.01"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="limit-shares">Shares</Label>
            <Input
              id="limit-shares"
              type="number"
              inputMode="decimal"
              min="0"
              step="1"
              value={limitShares}
              onChange={(e) => setLimitShares(e.target.value)}
              disabled={isTradingDisabled}
            />
          </div>
        </div>
      ) : side === "BUY" ? (
        <div className="space-y-1.5">
          <Label htmlFor="market-amount">Amount ($)</Label>
          <Input
            id="market-amount"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={marketAmount}
            onChange={(e) => setMarketAmount(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} above best ask
            {bestAsk !== null ? ` ($${bestAsk.toFixed(2)})` : ""}
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="market-shares">Shares to sell</Label>
          <Input
            id="market-shares"
            type="number"
            inputMode="decimal"
            min="0"
            step="1"
            value={limitShares}
            onChange={(e) => setLimitShares(e.target.value)}
            disabled={isTradingDisabled}
          />
          <p className="text-xs text-muted-foreground">
            Max slippage: {SLIPPAGE_CAP.toFixed(2)} below best bid
            {bestBid !== null ? ` ($${bestBid.toFixed(2)})` : ""}
          </p>
        </div>
      )}

      <dl className="space-y-1 rounded-md border bg-muted/30 p-3 text-xs">
        <Row label="Price" value={preview?.priceLabel ?? "—"} />
        <Row label="Shares" value={preview?.sharesLabel ?? "—"} />
        <Row label="Total" value={preview?.totalLabel ?? "—"} />
        {preview?.capWarning ? (
          <Row label="" value={preview.capWarning} muted />
        ) : null}
      </dl>

      <Button
        type="button"
        size="lg"
        disabled={!canSubmit}
        className="w-full"
        onClick={onSubmit}
      >
        {isTradingDisabled
          ? (disabledReason ?? "Trading disabled")
          : limitMutation.isPending
            ? "Placing…"
            : `${side === "BUY" ? "Buy" : "Sell"} ${outcome}`}
      </Button>
    </section>
  );
}

function Row({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "tabular-nums",
          muted ? "text-muted-foreground" : "font-medium",
        )}
      >
        {value}
      </dd>
    </div>
  );
}
```

- [ ] **Step 2: Edit `MarketDetailPage` to widen layout and mount the panels**

Replace the body of the returned JSX (keep the loading and error branches). The full updated file:

```tsx
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMarket } from "@/api/markets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { MarketState } from "@/types/market";
import { OutcomeChips } from "@/components/orders/OutcomeChips";
import { Orderbook } from "@/components/orders/Orderbook";
import { OrderTicket } from "@/components/orders/OrderTicket";

const STATE_STYLES: Record<MarketState, string> = {
  DRAFT: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
  ACTIVE:
    "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200",
  CLOSED: "bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200",
  RESOLVED: "bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-200",
  CANCELLED:
    "bg-rose-100 text-rose-900 dark:bg-rose-900/30 dark:text-rose-200",
};

export function MarketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: market, isLoading, error, refetch } = useMarket(id);

  const firstOutcome = useMemo(
    () => market?.erc1155_tokens[0]?.[1] ?? "",
    [market],
  );
  const [selectedOutcome, setSelectedOutcome] = useState<string>(firstOutcome);
  const outcome = selectedOutcome || firstOutcome;

  if (isLoading) {
    return <MarketDetailSkeleton />;
  }

  if (error || !market) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6">
        <p className="text-sm font-medium text-destructive">
          Failed to load market
        </p>
        <p className="text-xs text-muted-foreground">
          {error instanceof Error ? error.message : "Market not found"}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Retry
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/">Back to markets</Link>
          </Button>
        </div>
      </div>
    );
  }

  const isTradingDisabled = market.market_state !== "ACTIVE";
  const disabledReason = isTradingDisabled
    ? `Market is ${market.market_state}`
    : undefined;

  return (
    <article className="mx-auto max-w-5xl space-y-6">
      <Link
        to="/"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Back to markets
      </Link>

      <header className="space-y-3">
        <Badge
          variant="secondary"
          className={cn(
            "w-fit border-transparent",
            STATE_STYLES[market.market_state],
          )}
        >
          {market.market_state}
        </Badge>
        <h1 className="text-3xl font-bold tracking-tight">{market.question}</h1>
        {market.description ? (
          <p className="whitespace-pre-line text-sm text-muted-foreground">
            {market.description}
          </p>
        ) : null}
      </header>

      <OutcomeChips
        tokens={market.erc1155_tokens}
        selected={outcome}
        onSelect={setSelectedOutcome}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <Orderbook marketId={market.market_id} outcome={outcome} />
        <OrderTicket
          marketId={market.market_id}
          outcome={outcome}
          isTradingDisabled={isTradingDisabled}
          {...(disabledReason !== undefined ? { disabledReason } : {})}
        />
      </div>
    </article>
  );
}

function MarketDetailSkeleton() {
  return (
    <article className="mx-auto max-w-5xl space-y-6">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-5 w-20 rounded-full" />
      <Skeleton className="h-9 w-3/4" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </article>
  );
}
```

The `{...(disabledReason !== undefined ? { disabledReason } : {})}` shape is needed because `OrderTicketProps.disabledReason` is optional and `exactOptionalPropertyTypes` is on.

- [ ] **Step 3: Typecheck and unit tests**

```bash
cd ui && yarn typecheck && yarn test
```

Both should pass.

- [ ] **Step 4: Manual smoke test — Limit order end-to-end**

1. Start backend: from repo root, `uvicorn agentpit.api.main:app --host 0.0.0.0 --port 8000 --reload`. (Requires `make init` first.)
2. Start UI: `cd ui && yarn dev`.
3. Sign up a user via the existing AuthDialog.
4. Use the API to mint USDC and create an `ACTIVE` market with `["Yes", "No"]` outcomes if one doesn't exist:
   ```bash
   curl -X POST http://localhost:8000/mint_usdc \
     -H "Content-Type: application/json" \
     -d '{"api_key":"<your-key>","amount":1000}'
   ```
5. Open `/markets/<id>` in the browser. Confirm the layout has the orderbook on the left and the order ticket on the right (on `lg+` viewports).
6. With the ticket: select **Buy**, **Limit**, price **0.50**, shares **10**, click "Buy Yes". Toast appears. Orderbook ladder updates within ~3s with a new bid.
7. Click **Sell** + **Limit**, price **0.80**, shares **5** (you may need to `split_position` first to have shares). Toast appears. Ask ladder updates.
8. Log out, click submit again — the login dialog opens.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/orders/OrderTicket.tsx ui/src/pages/MarketDetailPage.tsx
git commit -m "$(cat <<'EOF'
feat(ui): wire OrderTicket Limit submit and mount on MarketDetailPage

Two-column lg+ layout (orderbook | ticket). Toast on success/error.
Invalidates orderbook and portfolio caches on successful place.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Wire `OrderTicket` Market submit via `placeMarketOrder`

**Files:**
- Modify: `ui/src/components/orders/OrderTicket.tsx`

- [ ] **Step 1: Add a second mutation and update the submit handler**

Inside `OrderTicket`, alongside `limitMutation`, add `marketMutation`. Replace the Market branch of `onSubmit`.

Insert this import addition at the top of the file:

```tsx
import { placeMarketOrder } from "@/api/orders";
```

Add `marketMutation` after `limitMutation`:

```tsx
const marketMutation = useMutation({
  mutationFn: async () => {
    if (!book) throw new Error("Orderbook not loaded yet");
    const amount = Number(side === "BUY" ? marketAmount : limitShares);
    return placeMarketOrder({
      marketId,
      outcome,
      side,
      amount,
      book,
    });
  },
  onSuccess: (res) => {
    const tail = res.cancelledRemainder
      ? ` (${res.remainingShares.toFixed(2)} unfilled, cancelled)`
      : "";
    const avg = res.avgPrice !== null ? ` @ avg $${res.avgPrice.toFixed(2)}` : "";
    if (res.filledShares <= 0) {
      toast.error(`No fills${tail || ""}`);
    } else {
      toast.success(
        `${side === "BUY" ? "Bought" : "Sold"} ${res.filledShares.toFixed(2)}${avg}${tail}`,
      );
    }
    if (res.cancelError) {
      toast.warning(`Auto-cancel failed: ${res.cancelError}`);
    }
    if (side === "BUY") {
      setMarketAmount("");
    } else {
      setLimitShares("");
    }
    invalidate();
  },
  onError: (err) => {
    toast.error(err instanceof Error ? err.message : String(err));
  },
});
```

Update `canSubmit` to include `marketMutation`:

```tsx
const canSubmit =
  !isTradingDisabled &&
  preview !== null &&
  !limitMutation.isPending &&
  !marketMutation.isPending &&
  (mode === "Limit" ||
    (side === "BUY" ? bestAsk !== null : bestBid !== null));
```

Replace the `onSubmit` handler:

```tsx
const onSubmit = requireAuth(() => {
  if (mode === "Limit") {
    limitMutation.mutate();
  } else {
    marketMutation.mutate();
  }
});
```

Update the button label section to consider `marketMutation.isPending`:

```tsx
{isTradingDisabled
  ? (disabledReason ?? "Trading disabled")
  : limitMutation.isPending || marketMutation.isPending
    ? "Placing…"
    : `${side === "BUY" ? "Buy" : "Sell"} ${outcome}`}
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && yarn typecheck
```

- [ ] **Step 3: Manual smoke test — Market order**

1. Start backend + UI as in Task 13.
2. With two different signed-in users (use two browsers or an incognito window), have user **A** place a **Limit SELL** of 50 YES @ $0.70 — this creates resting asks.
3. As user **B** (with USDC), open the same market, select **Buy**, **Market**, type `$10`. Preview shows `Price ≤ $0.72` and `Shares ~13.89`. Submit.
4. Toast: `Bought 13.89 @ avg $0.70` (or close to it, depending on book composition). Orderbook updates: A's resting ask shrinks.
5. As user **B**, switch to **Sell**, **Market**, type `5` shares (you may need to split_position first). If no bids exist, submit is disabled with "No bids available" preview. Otherwise toast on fill.
6. Slippage clamp check: place an ask at `$0.98` from user A, then as user B do **Buy Market $5`. Preview shows `Cap clamped to 0.99` and the order fills at `0.98`.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/orders/OrderTicket.tsx
git commit -m "$(cat <<'EOF'
feat(ui): wire OrderTicket Market submit via placeMarketOrder

Toast surfaces filled shares + avg price + cancelled-remainder summary.
Auto-cancel failures are non-fatal warnings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Final manual smoke test pass + fixups

**No file changes by default.** This task walks the full smoke test plan from the spec; any bugs discovered get fixed in this task as separate commits.

- [ ] **Step 1: Run the full smoke test**

Follow `docs/superpowers/specs/2026-05-12-order-placement-ui-design.md` § *Manual smoke test plan*. Steps:

1. Sign up user A. Mint 1000 apUSD.
2. Sign up user B. Mint 1000 apUSD.
3. Both users: `split_position(100)` on the same `ACTIVE` market.
4. User A places Limit SELL 50 YES @ $0.70. Toast = "0 filled, 50 resting".
5. User B places Limit BUY 30 YES @ $0.70. Toast = "30 filled". Orderbook: A's ask shrinks to 20.
6. User B places Market BUY $20 of YES. Verify fill against A's ask up to slippage cap or budget.
7. User A places Market SELL 5 YES. Verify against B's bids.
8. Log out, click any submit button → login dialog opens; no order placed.
9. Refresh the page mid-resting-order — orderbook reflects DB state.

- [ ] **Step 2: Run final typecheck + unit tests + lint**

```bash
cd ui && yarn typecheck && yarn test && yarn lint
```

All three must pass.

- [ ] **Step 3: If any fixes were committed, push branch and open PR**

```bash
git push -u origin ui
gh pr create --title "feat(ui): order placement on market detail page" \
  --body "$(cat <<'EOF'
## Summary
- Adds order ticket (Limit + Market BUY/SELL) and live orderbook to `MarketDetailPage`
- Slippage-capped Market orders place a GTC limit then best-effort cancel the unfilled remainder
- Pure-function math in `orderMath.ts` covered by Vitest unit tests
- No backend changes

Spec: `docs/superpowers/specs/2026-05-12-order-placement-ui-design.md`
Plan: `docs/superpowers/plans/2026-05-12-order-placement-ui.md`

## Test plan
- [ ] `yarn typecheck` passes
- [ ] `yarn test` passes (orderMath unit tests)
- [ ] `yarn lint` passes
- [ ] Manual: limit buy + sell against an active market
- [ ] Manual: market buy fills + auto-cancels remainder
- [ ] Manual: market submit disabled with empty book
- [ ] Manual: logged-out submit opens login dialog

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(Skip the PR step if the user has not yet asked to push.)

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `types/order.ts` types | Task 2 |
| `orderMath.ts` with shares↔dollars + market computations | Tasks 3, 4, 5 |
| `api/orders.ts` placeOrder, cancelOrder | Task 6 |
| `useOrderbook` 3s polling, focus-aware | Task 7 |
| `placeMarketOrder` two-step | Task 8 |
| Sonner toasts wired | Task 9 |
| OutcomeChips component | Task 10 |
| Orderbook component with 8-deep ladder | Task 11 |
| OrderTicket Buy/Sell × Limit/Market | Tasks 12, 13, 14 |
| `useRequireAuth` wrap on submit | Task 13 |
| Invalidate orderbook + portfolio on success | Task 13 |
| Widen MarketDetailPage to `max-w-5xl`, two cols | Task 13 |
| Disable inputs when market not ACTIVE | Task 13 (in MarketDetailPage) |
| Empty-book disables Market submit | Task 14 (via `canSubmit` + preview returning null) |
| Vitest unit tests on orderMath | Tasks 3, 4, 5 |
| Manual smoke test plan | Task 15 |
| 401 mid-session handled | Already in `api/client.ts:36` — no task needed |

**Placeholder scan:** no TBDs, all code blocks complete, all file paths exact, all expected outputs stated.

**Type/name consistency:** `MarketOrderResult.cancelError` is `string | undefined` (optional, only assigned when present per `exactOptionalPropertyTypes`); used consistently in `placeMarketOrder` and the Task 14 mutation. `SHARES_SCALE = 1_000_000` referenced from the same module in three places. `placeMarketOrder` arg name `book: OrderbookResponse` matches what `useOrderbook` returns. `OrderTicketProps.disabledReason` is optional and only spread when defined in MarketDetailPage.

One acceptable simplification flagged: in Task 13, `MarketDetailPage` passes `outcome` directly from local state; if the user navigates to a market with different labels (e.g. `["Yes", "No", "Maybe"]`) the chip selector handles it but the page initial-state `firstOutcome` covers the common binary case.
