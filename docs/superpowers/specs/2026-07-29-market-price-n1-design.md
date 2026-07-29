# Market probabilities: remove the per-market book fan-out — Design

**Date:** 2026-07-29 · **Repo:** agentpit, branch `mvp` (UI-only) · **Status:** approved by user (prices from the list payload everywhere, including the event page's Yes/No chips)

## Problem

Opening the home page or an event page is slow, and the probability percentages
appear seconds after the rest of the page. Measured against production
(23.88.62.130) in a real browser:

| Page | API requests | of which `GET /book` | last response |
|---|---|---|---|
| Home | 210 | **203** | **17.4 s** |
| Event (26 markets) | 70 | **58** | **13.3 s** |

A single `GET /book` takes 0.26 s on its own; the 2.4 s average is queueing —
the browser allows ~6 concurrent connections per host and the page asks for 203.

**The requests are redundant.** The server already derives prices for every
market in the list in two DB round-trips (`prices_for_markets` →
`compute_market_prices`, `agentpit/polymarket/pricing.py:88`) and ships them in
the Gamma payload as `outcomePrices`, `bestBid`, `bestAsk`, `lastTradePrice`.
The UI's `GammaMarket` type already declares those fields
(`ui/src/types/gamma.ts:10,22-24`), but `gammaToMarket`
(`ui/src/api/markets.ts:15-34`) drops them, after which four display paths
re-derive the same numbers one market at a time.

The server's price is also **better**: `compute_market_prices` falls back to the
outcome's last trade, then to the binary complement, then to 0.5, while the
client's `computeMid` only averages the book top — which is why single-sided
markets show no percentage at all today.

Caching was the user's first instinct; it is the wrong tool here. The calls are
already cheap individually, and a cache would not speed up the first load, which
is the complaint.

## Server-side contract (verified, not assumed)

`MarketPrices` (`agentpit/polymarket/pricing.py:17-28`) documents the semantics
the UI will now rely on:

- `outcome_prices` — one price per outcome, aligned to `erc1155_tokens`.
- `best_bid` / `best_ask` / `last_trade` — **describe outcome[0] (YES)**, matching
  Gamma's scalar fields. There is exactly one bid/ask pair per market, by design:
  Polymarket's own Gamma shape has one, and this API keeps parity.

## Design

Carry the price with the market instead of fetching it separately.

### 1. Data flow

- `ui/src/types/market.ts` — `Market` gains:
  - `outcome_prices: number[]` — one probability in [0, 1] per outcome, index-aligned with `erc1155_tokens`.
  - `best_bid: number | null` and `best_ask: number | null` — the YES side's touch, needed by the Yes/No chips.
- `ui/src/api/markets.ts` — `gammaToMarket` parses `g.outcomePrices` (a
  JSON-encoded string array, e.g. `"[\"0.62\",\"0.38\"]"`) into numbers and
  copies `g.bestBid` / `g.bestAsk`. Malformed, absent, or non-numeric input
  yields `[]` / `null` rather than throwing — these fields are presentational
  and must never break a render. The server sends `0.0` for "no book", which
  maps to `null` so a missing touch is never displayed as a real 0¢ price.

### 2. Call sites that stop fetching (all 203 + 52 requests)

| File | Today | After |
|---|---|---|
| `components/MarketCard.tsx:32` | `useOutcomeMid(yesTokenId)` — 1 book request per card | `market.outcome_prices[0]` |
| `components/MultiMarketEventCard.tsx:69` | `useYesMidMap(markets)` — 1 per child market | map built from `markets` in memory |
| `pages/EventDetailPage.tsx:48` | `useYesMidMap(data.markets)` | map built from `data.markets` in memory |
| `components/EventLeaderboardRow.tsx:58-59` | `useOutcomeMid` ×2 (YES and NO) per row | big % ← `outcome_prices[0]`; Yes chip ← `best_ask`; No chip ← `1 − best_bid` |

**Accepted fidelity change (user-approved), one place only.** The No chip shows
the price to buy NO. Today that is the NO book's own best ask, falling back to
`1 − yesBid` (`deriveNoAsk`, `components/orders/orderMath.ts:35-43`). With one
bid/ask pair in the payload, it becomes the fallback branch always: `1 − best_bid`.
That is the true cost of acquiring NO through the YES book, and the two agree
whenever the books are mirrored consistently; they can differ by a fraction of a
cent when the NO book carries its own resting asks.

`useYesMidMap` and `useOutcomeMid` lose their last consumers and are deleted;
`ui/src/lib/useYesMid.ts` disappears with them, along with `computeMid` and
`deriveNoCents`, whose only remaining callers are that module's own tests
(`ui/src/lib/useYesMidMap.test.ts`, deleted with it). `deriveNoAsk` also loses
its only production caller but **stays** — it is covered by
`components/orders/orderMath.test.ts` and belongs to the order-math module that
`OrderTicket` and `Orderbook` still use. `bestAsk` / `bestBid` stay for the same
reason.

The live order book remains where it is genuinely needed: `OrderTicket` and
`Orderbook` on the market detail page. That is one book request, not N.

### 3. Freshness (a required compensating change)

Today the displayed percentage stays current only because the book queries poll
every 30 s. `useMarket` and `useEvent` do **not** poll
(`ui/src/api/markets.ts:54-65`, `ui/src/api/events.ts:105-114`), so moving the
price onto the market object would freeze the number at page-load time on the
market and event detail pages.

Both hooks therefore gain `refetchInterval: 30_000` with
`refetchIntervalInBackground: false` — the cadence the book queries used, at one
request per page instead of N. The home grid needs no change: its
`useEventsInfinite` already polls every 5 s, so its percentages become *fresher*
than the 30 s they have today.

### 4. Testing

- Vitest on `gammaToMarket`: a well-formed `outcomePrices` maps to numbers in
  order; `"[]"`, `""`, malformed JSON, and non-numeric entries yield `[]` without
  throwing; `bestBid`/`bestAsk` of `0.0` map to `null`, non-zero values pass
  through.
- Vitest on the No-chip derivation: `1 − best_bid` in cents, and `null` when
  `best_bid` is `null`.
- Existing `orderMath` tests stay untouched.
- Verification is a real browser measurement against the deployed UI, repeating
  the method that produced the numbers above: home page API requests must drop
  from ~210 to ~7 and the event page from ~70 to ~7, with percentages present in
  the first render. Record before/after counts.

## Out of scope

- Batching `prices-history` (11 requests on the event page — sparklines).
- A server-side TTL cache for `/book` or `/prices-history`.
- Any backend change: every field this needs is already in the payload.

## Correction (post-ship review, 2026-07-29)

The final review found this design understated its user-visible surface. It is
not just the No-chip fidelity change in §2 — two more changes ship with it:

**(a) The event page's auto-expanded row now selects a different market.**
Before this change, `useYesMidMap` returned an empty map on the first render
that had data, so `ordered` (`sortMarketsByYesMid`) was still payload order on
that render, and `autoSelectedSlugRef` in `EventDetailPage` latched onto
`markets[0]` — whichever market Gamma happened to list first, not the most
likely outcome. Now `yesPriceMap` is populated synchronously from the same
render that has `data`, so `ordered[0]` is genuinely the top-probability
market and that is what gets auto-selected. This matches the code's own
stated intent at `ui/src/pages/EventDetailPage.tsx:64-66` ("otherwise the
top-ranked outcome") — the comment was already describing the desired
behavior, the implementation just raced it on first paint. It already
happened correctly when navigating from a warm home page (react-query cache
hit → synchronous data on mount), so this is an accidental fix of a
first-load-only bug, not a new behavior — it should not be reverted.

The same root cause makes `EventChart`'s top-4 series pick
(`pickChartSeries(markets, midByMarket, CHART_PALETTE, 4)`) stable from first
paint instead of reshuffling as individual book requests landed and
`midByMarket` grew entry by entry.

**(b) The "no price" state is now effectively unreachable, not merely rare.**
The design above (and the plan) treats a market with no book and no tape as
still producing `null`/absent prices, rendered as a dimmed em dash. That is no
longer true of the server this UI talks to: `_price_fields`
(`agentpit/polymarket/gamma.py:40-47`) falls back to `outcomePrices:
["0.5", ...]`, `bestBid: 0.0`, `bestAsk: 0.0` whenever there is no
`MarketPrices` or an outcome-count mismatch, and `compute_market_prices`
(`agentpit/polymarket/pricing.py:69-75`) falls back further, per outcome, to
the binary complement and then to `PRICE_ONE // 2` (0.5) — there is no path
through either function that omits `outcomePrices` or leaves an outcome
price absent. The server **always** emits a price. A market with no book and
no tape therefore renders a confident, undimmed "50" — not the dimmed "—" a
genuinely-missing price would produce. As of this review, 0 of 203 production
markets hit this path.

The UI's defensive "no price" branches — `formatProbabilityPct(null)` → "—",
`MarketCard`'s `outcome_prices[0] === undefined` dim check,
`EventLeaderboardRow`'s `yesMid === null` dim check, and
`sortMarketsByYesMid`'s "unknown mid sorts last" branch in
`ui/src/lib/eventOutcomes.ts` — are kept deliberately, even though none of
them currently fire against this server. They are correct for the `Market`
type's actual contract (`outcome_prices: number[]`, which can be `[]`, and
`best_bid`/`best_ask: number | null`) and for any payload that doesn't carry
the server's always-fill-0.5 guarantee (a different backend, a test fixture,
a future change to `_price_fields`). Removing them would be optimizing for
one server implementation detail rather than the type the UI actually
declares.
