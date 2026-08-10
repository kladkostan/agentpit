# Sync the whole event, and stop calling a live market resolved

**Status:** approved 2026-08-10
**Follows:** `docs/superpowers/specs/2026-08-10-overdue-live-markets-design.md` (shipped)

## Problem

Two defects, both visible on one card.

### 1. A 33-outcome event is represented by one outsider

The previous change admitted "Will Adanech Abiebie be the next Prime Minister of
Ethiopia?" — the market a user reported missing. It arrived alone. Its event,
`Next Prime Minister of Ethiopia?`, has 33 outcomes upstream and $273M of
lifetime volume, and our card shows a single candidate at **<1%** beside
`$273.1M VOL` — the event's whole volume attached to an outcome nobody expects
to win. The favourite is not on the site at all.

The cause is arithmetic, not a bug: the sync takes the top 1000 individual
markets by 24h volume, and the cutoff is $3,053. Exactly **1 of the event's 33
outcomes** clears it; the next has $1,033 and the rest are near zero. An event
is one question, and half an answer to it is worse than none.

Measured across the whole window: the top-1000 markets belong to **414 distinct
events** holding **5,990 open outcomes** between them.

### 2. `Awaiting resolution` is the wrong thing to say

The previous change made an overdue market's card read `AWAITING RESOLUTION`.
That copy was mine and it is wrong. Checked against upstream while writing this:

```
closed False | active True | acceptingOrders True | enableOrderBook True
volume24hr 678,363
```

The market is open and trading. Its *deadline* lapsed, not the market. The card
tells a reader the position is settled when they can still take one.

## Design

### Pull the event, capped

After the market window is fetched, collect the distinct events those markets
belong to and pull each event's other open outcomes, keeping the **top 12 by 24h
volume**. Every filter that applies to a primary-window market applies unchanged
to a sibling — the liquidity floor, `closed`, the expiry rule. The market that
qualified on its own merit is always kept, whatever the cap.

**Why 12.** The median event has 11 open outcomes, so the cap is set just above
it: 270 of the 414 events come through whole, and only 144 are truncated — the
long-tail monsters, of which the largest have 128 outcomes. Truncating those is
not a compromise. Keeping the top outcomes by volume is what Polymarket's own
interface does, and the event card already renders `+ N MORE OUTCOMES`.

**Measured cost**, against the 1000 markets a pass takes today:

| | markets per pass | vs today |
| --- | --- | --- |
| no cap | 5,990 | 6.0x |
| cap 12, no floor | 3,345 | 3.3x |
| **cap 12, with the existing $5,000 floor** | **2,302** | **2.3x** |

The floor removes 1,043 sibling markets and is what makes this affordable. It is
not a compromise either: applied to the Ethiopia event it keeps 8 outcomes and
drops 4, and the 4 are `Person C`, `Person D`, `Person E`, `Person F` — zero
liquidity, zero volume, placeholders upstream keeps for unnamed candidates.
The 8 kept are the real candidates, including the incumbent.

The liquidity mirror quotes every ACTIVE synced market — 2,844 today — so 2.3x
is a real cost paid by the liquidity engine, not just storage. The cap belongs
in configuration (`SYNC_EVENT_MAX_OUTCOMES`, default 12) so it can be lowered
without a deploy if the mirror struggles.

**Mechanism.** Gamma's `/events?id=` endpoint, batched — the same idiom
`scripts/backfill_market_tags.py` already uses. 414 events at 40 ids per call is
about 11 extra requests per sync pass.

**Nothing else about the window changes**: `order=volume24hr`, the 1000-market
primary cap, and `max(liquidity, volumeNum) >= 5000` all stay. Switching the
sort key to lifetime volume was measured and rejected in the previous spec.

**Events need no new wiring.** Each market payload already carries
`events[0]`, and `polymarket_sync.py:424-442` reads `polymarket_event_id` from
it and upserts the event. Siblings attach to the same event on their own.
`create_polymarket_markets_if_needed` is create-only and skips markets it has
seen, so re-running is idempotent and no existing market is disturbed.

### Say what is actually true on the card

Replace `Awaiting resolution` with `OVERDUE` followed by the lapsed date, in the
same slot and the same shape as its neighbours:

```
CLOSES NOV 7      a normal market
OVERDUE JUN 1     the deadline lapsed; the market is still trading
```

This keeps the date — a reader can see how far it has slipped — and drops the
claim that the outcome is settled. The gate is unchanged and must stay
unchanged: the label appears only when the date has passed **and** the state is
ACTIVE. Production has 849 past-dated events that are fully resolved, and they
must keep printing their date.

All four call sites shipped in the previous change take the new copy: both
cards and both detail pages.

## Out of scope

- The sync's ordering, primary cap and liquidity floor.
- Anything about how the mirror chooses what to quote. If 2.3x proves too much,
  the lever is `SYNC_EVENT_MAX_OUTCOMES`, and finding a better lever is its own
  piece of work.
- Backfilling events already in the catalogue as single-outcome fragments. New
  passes will fill them in as their events come up; a one-time backfill can
  follow if it turns out to matter.

## Testing

- An event whose top outcome qualifies contributes its top 12 open outcomes by
  24h volume, and no more.
- A sibling below the liquidity floor is dropped; a sibling above it is kept.
- The market that qualified on its own is kept even if the cap would exclude it.
- A closed sibling is never pulled.
- The cap is read from configuration, and setting it to 1 reproduces today's
  behaviour for the event's own outcome.
- `closeLabel` returns `OVERDUE` + the formatted date for a past date on an
  ACTIVE thing, and the plain date for every finished state — the 849-event
  regression stays covered.

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` (never
source `.env`; the local anvil must be running). UI, from `ui/`:
`npx vitest run && npm run typecheck && npm run lint && npm run build`.
