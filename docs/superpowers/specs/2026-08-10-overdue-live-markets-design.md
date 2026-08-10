# Overdue but still trading — design

**Status:** approved 2026-08-10

## Problem

A user asked why "Next Prime Minister of Ethiopia?" is missing from agentpit
despite $273M of volume. It is missing because our own sync throws it away.

`agentpit/polymarket/polymarket_sync.py:299`:

```python
if not closed and _is_market_expired(m):
    continue
```

`_is_market_expired` looks only at `end_date_iso`. The market's biggest outcome,
"Will Adanech Abiebie be the next Prime Minister of Ethiopia?", carries
`endDate: 2026-06-01` — a date over two months past. Polymarket itself reports
`closed: false`, `active: true`, `acceptingOrders: true`, and $678,358 of volume
in the last 24 hours. The deadline lapsed; the question did not.

### Measured on production, 2026-08-10

Of the top-1000 markets by `volume24hr` — the exact window the sync fetches:

| | |
| --- | --- |
| dropped for a past end date | **28** |
| of those, still accepting orders | **28** — all of them |
| their combined 24h volume | $1,844,437 |
| their combined lifetime volume | $95,880,067 |

The class is rolling-deadline geopolitics: the Ethiopia market, `US x Iran
Effective Ceasefire by July 31?` ($389k/24h), `Israel x Iran ceasefire continues
through August 9?` ($388k/24h), `Kharg Island no longer under Iranian control`
($112k/24h). Exactly the markets people watch.

### What this is NOT

The sync fetches `order=volume24hr`, capped at `SYNC_MAX_MARKETS` (1000 on
production). It is tempting to blame that window, since the reported figure —
$273M — is *lifetime* volume. It is not the cause: the Adanech market ranks
**#5 of 1000 by 24h volume**. It has been inside the window the whole time.

Changing the sync key was considered and rejected on measurement. A second
window keyed on lifetime volume (`order=volumeNum`; note `order=volume` is NOT
lifetime volume — it returns 100, 1000, 100 and must never be used) would admit
747 markets that are large historically and dead now:

| window | median 24h volume, ranks 751-1000 | markets under $100/24h |
| --- | --- | --- |
| top-1000 by `volume24hr` | $3,752 | **0 of 1000** |
| top-1000 by `volumeNum` | $115 | **338 of 1000** |

Every market in the 24h window is actively trading; a third of the lifetime
window is not. The 24h key already selects for what this product wants. Nothing
about the sync's ordering or cap changes.

## The fix

### 1. Upstream decides whether a market is over, not its stated date

Replace the date-only test with one that defers to Polymarket. A market is
excluded only when its end date has passed **and** upstream has stopped
accepting orders. When `acceptingOrders` is absent from the payload — older
Gamma shapes, fixtures — fall back to the current date-only behaviour, so
existing expectations are preserved rather than silently loosened.

`acceptingOrders` is not currently normalized; it must be added to
`_normalize_market_fields` alongside `active` / `closed` / `archived`, including
their bool-ish string coercion.

The existing `closed` check above stays exactly as it is. It is orthogonal: it
catches markets Gamma leaks despite `closed=false`.

### 2. The stored end date does not change

`END_DATE` is written from upstream as-is. No schema change, no backfill.

`EventSort.ENDING_SOON` keeps its `(END_DATE IS NULL OR END_DATE >= NOW())`
predicate untouched. An overdue market correctly drops out of that sort: it is
not "ending soon", it is already past due, and surfacing it there would push
genuinely-closing markets down.

### 3. The interface stops printing a date that has passed

`MarketCard.tsx:41` and `MultiMarketEventCard.tsx:85` both render
`formatShortDate(end_date)`. On an overdue market that prints "Jun 1" beside a
live order book — the card contradicts itself.

Where the end date has passed **and the thing is still tradable**, render
`Awaiting resolution` in place of the date — that exact string, in both
components, replacing the whole date value rather than annotating it. The
surrounding label ("Closes") is replaced along with it, since nothing is
closing.

**The gate must include state, not just the date.** On production today:

| | events |
| --- | --- |
| past end date, still has an ACTIVE market | **50** |
| past end date, everything resolved | **849** |

Gating on the date alone would make 849 finished events claim they are awaiting
resolution. The state is already at hand in both components: the event card
computes `eventState(markets)` (`ui/src/lib/marketState.ts:31`) and the market
card reads `market.market_state`. Both already drive a badge tone; this reuses
the same value rather than deriving a second notion of liveness.

## What this does not touch

**The resolution mirror is already safe** and needs no guard.
`TableRead.list_unresolved_ended_markets` selects candidates by past `END_DATE`,
so these markets join every pass — but `_winner_index_if_resolved` requires the
upstream document to say `closed` with a winning token, and upstream says
`closed: false`. They are fetched every `RESOLUTION_MIRROR_INTERVAL_SECONDS`
(300 on production) and correctly skipped, forever, until upstream really
closes them. That is wasted work at a rate of 28 fetches per pass, not a
correctness risk, and it is deliberately left alone.

**The sync's ordering, cap and liquidity floor are unchanged** — `volume24hr`,
`SYNC_MAX_MARKETS=1000`, `max(liquidity, volumeNum) >= SYNC_LIQUIDITY_MIN=5000`.

**No new catalogue growth beyond the 28 markets this admits.** The liquidity
mirror quotes every ACTIVE synced market (2,844 today), so catalogue size has a
real cost; this change adds to it only markets that are genuinely trading.

## Testing

- A market past its end date but `acceptingOrders: true` is admitted; the same
  market with `acceptingOrders: false` is dropped; a market with no
  `acceptingOrders` key at all falls back to the date rule. These three are the
  whole of the backend change.
- `_normalize_market_fields` coerces `acceptingOrders` from both a bool and the
  string forms it arrives as.
- The UI label is chosen on (past date AND tradable state) and NOT on the date
  alone — the 849-event trap above is the regression to guard.

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` (never
source `.env`; the local anvil must be running). UI, from `ui/`:
`npx vitest run && npm run typecheck && npm run lint && npm run build`. Note
`ui/` vitest runs in a node environment with no `@testing-library/react`, so
components cannot be render-tested — the label decision must live in a pure
helper that can be tested directly.
