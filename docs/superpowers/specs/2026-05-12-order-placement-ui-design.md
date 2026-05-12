# Order Placement UI — Design

**Date:** 2026-05-12
**Scope:** Frontend-only. Adds a Polymarket-style order ticket and live orderbook to `MarketDetailPage` so authenticated users can buy and sell YES/NO outcome tokens.

## Goals

- Logged-in users can place **limit** and **market** orders on any `ACTIVE` market from the market detail page.
- Live orderbook (bids + asks) for the selected outcome is visible next to the ticket.
- No backend changes. Existing endpoints (`POST /orders`, `DELETE /orders/{id}`, `GET /orderbook/{market_id}/{outcome}`) are sufficient.
- Unauthenticated clicks open the login dialog; they do not lose state silently.

## Non-goals

- "My open orders" panel and recent trades feed (deferred — see Polymarket parity backlog).
- Order-type selectors beyond Limit / Market (no GTD/FOK/FAK UX — backend only honors GTC).
- Charts, comments, mobile-first layouts beyond responsive stacking.
- Optimistic UI / websocket order updates (polling is good enough at this stage).

## Input model

| Tab | BUY inputs | SELL inputs |
|---|---|---|
| Limit | `Limit Price` ($) + `Shares` | `Limit Price` ($) + `Shares` |
| Market | `Amount` ($) | `Shares` |

All four cases derive the wire payload `(price, size)`:

- `size` is always outcome-token quantity scaled by `10^6`.
- For Limit: `price` and shares come straight from inputs.
- For Market BUY: `price = best_ask + 0.02` (slippage cap, clamped to ≤ 0.99); `size = floor(amount / price × 1_000_000)`.
- For Market SELL: `price = best_bid - 0.02` (clamped to ≥ 0.01); `size = shares × 1_000_000`.

The slippage cap is a fixed `0.02` constant in `orderMath.ts`. Not user-configurable in v1.

## Architecture

Frontend-only, three new files plus an edit to `MarketDetailPage`.

```
ui/src/
├── api/
│   └── orders.ts              [new]
├── types/
│   └── order.ts               [new]
├── components/
│   └── orders/                [new dir]
│      ├── OrderTicket.tsx
│      ├── Orderbook.tsx
│      ├── OutcomeChips.tsx
│      └── orderMath.ts        pure functions; no React
└── pages/
    └── MarketDetailPage.tsx   [edit] widen to max-w-5xl, mount the two panels
```

Layout on `lg+`: two columns. Left = outcomes table + orderbook. Right = sticky order ticket. Stacks vertically below `lg`.

### Components

- **`OutcomeChips`** — controlled toggle for `"YES" | "NO"` (or whatever labels the market exposes). Source of truth for which outcome both panels are showing. Lives in `MarketDetailPage`.
- **`Orderbook`** — top 8 bids and top 8 asks for the selected outcome. Calls `useOrderbook(marketId, outcome)`. Empty state: "No resting orders for this outcome." On poll failure: keep stale data, show a subtle "stale" hint.
- **`OrderTicket`** — Buy/Sell tab × Limit/Market tab. Inputs per the model above. Live preview (avg price, total cost, balance check). Submit button wrapped in `useRequireAuth`. On success: toast + invalidate `["orderbook", marketId, outcome]` and `["portfolio", apiKey]` if present.
- **`orderMath.ts`** — pure: `sharesFromDollars(amount, price)`, `dollarsFromShares(shares, price)`, `computeMarketBuy(bookAsks, amount, slippageCap)`, `computeMarketSell(bookBids, shares, slippageCap)`, formatters.

### API layer

```ts
// api/orders.ts
export async function placeOrder(req: PlaceOrderRequest): Promise<OrderResponse>
export async function cancelOrder(orderId: string): Promise<void>
export function useOrderbook(marketId: number, outcome: string)  // 3s polling, focus-aware
export async function placeMarketOrder(args): Promise<MarketOrderResult>
```

`placeMarketOrder` is the wrapper for the Market two-step:

1. Read current orderbook from cache (refresh if `dataUpdatedAt` is stale > 5s).
2. Derive `(price, size)` via `orderMath.ts`.
3. `placeOrder(...)` as a GTC limit.
4. If `response.remainingSize > 0 && response.status === "live"`: `cancelOrder(response.orderID)`. Best-effort — log + toast warning on cancel failure but do not throw.
5. Return `{ filled, remaining, avgPrice, txHash, cancelledRemainder }`.

## Data flow

```
MarketDetailPage
   │
   ├── useMarket(id)                  (existing)
   ├── OutcomeChips ─── selectedOutcome (local state)
   │       │
   │       ├──► Orderbook ── useOrderbook(marketId, outcome) ── polls 3s
   │       │                                                    invalidated on submit
   │       └──► OrderTicket ── useMutation(placeOrder | placeMarketOrder)
   │                            on success → invalidate orderbook + portfolio
   │
   └── useAuth() → requireAuth wrap on the submit button
```

## Error handling

| Case | Handling |
|---|---|
| Not logged in | `useRequireAuth` opens login dialog; submit no-op. |
| Market not `ACTIVE` | Inputs disabled, banner: "Market is `<state>`. Trading paused." |
| Insufficient USDC (BUY) | Pre-flight check against `useAuth().user` balance if available; inline error under amount. Server check is still authoritative. |
| Insufficient shares (SELL) | Same shape as above, against the user's position for the selected token. |
| Price ≤ 0 or ≥ 1 in Limit | `<input>` `min`/`max` + inline error; submit disabled until valid. |
| Empty book on Market submit | Submit disabled with hint: "No liquidity — use a limit order." |
| Slippage cap clamped to 0.99 / 0.01 | Show the clamped price in the preview so the user knows. |
| `placeOrder` returns `success: false` | Toast with `errorMsg`; do not invalidate orderbook. |
| Auto-cancel DELETE fails | Toast warning: "Order placed; auto-cancel of the unfilled portion failed — you can cancel manually." Surface order ID. |
| Orderbook poll fails | Soft fail — keep last good data, render "stale" hint. |
| 401 mid-session | Existing `UNAUTHORIZED_EVENT` in `client.ts:36` clears local auth state. No new code needed. |

## Race conditions

Approach A accepts one bounded race: between `POST /orders` and the conditional `DELETE` for Market orders, another taker may match against the remainder. The DELETE then fails or no-ops on an already-`matched` row. Worst case is a partially-filled order behaving like a tiny resting limit. This is a documented tradeoff, not a bug.

## Testing

### Automated

- **Vitest** added to `ui/`. New dev dep: `vitest`, `@vitest/coverage-v8` (optional). Script: `"test": "vitest run"`.
- **Unit tests on `orderMath.ts`** covering:
  - `sharesFromDollars` / `dollarsFromShares` round-trip and rounding at 1¢ boundaries.
  - `computeMarketBuy` with an empty book → returns `null`.
  - `computeMarketBuy` with a book where the slippage cap would exceed 0.99 → clamped.
  - `computeMarketSell` analog with the lower bound clamp at 0.01.
  - Small-size and decimal-precision edge cases (e.g. `amount=$0.50, price=0.66`).
- **Typecheck gate:** `yarn typecheck` must pass.

### Manual smoke test plan

Run against a fresh `:memory:` server with two users for matching:

1. Sign up user A. Mint 1000 apUSD.
2. Sign up user B. Mint 1000 apUSD.
3. Both users: `split_position(100)` on the same `ACTIVE` market so each has 100 YES + 100 NO.
4. User A places **Limit SELL** 50 YES @ $0.70 → toast shows "0 filled, 50 resting". Orderbook shows the ask.
5. User B places **Limit BUY** 30 YES @ $0.70 → toast shows "30 filled". Orderbook updates. User A's resting size shrinks to 20.
6. User B places **Market BUY** $20 of YES. Verify: filled at A's $0.70 ask up to either the slippage cap or the dollar budget; remaining (if any) auto-cancels.
7. User A places **Market SELL** 5 YES. Verify symmetrical behaviour against B's bids (if any) or "no liquidity" disabled state.
8. While logged out, click any submit button → login dialog opens; no order placed.
9. Refresh the page mid-resting-order — orderbook reflects DB state.

## Implementation order

A suggested execution sequence (not committing to it — `writing-plans` will refine):

1. `types/order.ts` + `api/orders.ts` (no UI yet).
2. `orderMath.ts` + Vitest setup + unit tests.
3. `Orderbook.tsx` with `useOrderbook` polling; wire into `MarketDetailPage` behind a feature-flag-free conditional on `market.market_state === "ACTIVE"`.
4. `OutcomeChips.tsx`.
5. `OrderTicket.tsx` Limit tab only; verify end-to-end against running backend.
6. Market tab + `placeMarketOrder` two-step.
7. Manual smoke test pass; commit.

## Open questions / explicit non-decisions

- **No retry/backoff on the auto-cancel DELETE.** First call only. If users see frequent failures we revisit.
- **Slippage constant** could move to env / settings later. Today it lives in `orderMath.ts`.
- **Position cache** for the SELL share-balance check: the portfolio endpoint exists, but the UI does not currently cache it. Either fetch on ticket mount or skip the client-side check entirely. Decided: skip for v1; rely on server-side check. Reduces complexity; we surface the error from the response instead.
