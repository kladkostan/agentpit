# Deep order book: hot band + slow cold sweep — Design

**Date:** 2026-07-29 · **Repo:** agentpit, branch `mvp` (backend-only) · **Status:** approved by user (cap 50 levels/side, hot 8, cold sweep every 30 min)

## Problem

Every mirrored market shows exactly 8 levels per side. The user wants the whole
book visible, with the deep levels refreshed rarely rather than continuously.

The 8 is `AGENTPIT_MIRROR_BOOK_DEPTH` (`agentpit/config.py:197`, default 8),
applied in `desired_levels` (`agentpit/liquidity/reconciler.py:41-58`) as a
slice of the upstream snapshot. Nothing downstream truncates: `get_book`
(`agentpit/services/order_service.py:458-468`) aggregates **all** live orders
for a token with `GROUP BY SIDE, PRICE` — no owner filter, no depth cap — and
`ui/src/components/orders/Orderbook.tsx` renders whatever it receives. Verified
on production: our book returns exactly 8/8 while the upstream book has far more.

**Real upstream depth**, sampled across 20 top-volume Polymarket markets:
median **40** levels per side, mean 43, max **124**. Each mirrored level becomes
4 orders (`desired_levels` emits YES BUY + NO SELL from a bid, YES SELL + NO BUY
from an ask), so a fully mirrored median market holds ~160 resting orders against
today's 32.

## What this does NOT require (verified, saves half the work)

- **No extra on-chain inventory.** `_ensure_inventory`
  (`reconciler.py:111-125`) sizes its split-mint from `split_target_micro(snap)`
  (`reconciler.py:84-90`), which sums the **full** snapshot's ask side — not the
  depth-limited slice. The house already mints inventory for the entire upstream
  book and merely declines to post most of it.
- **No UI or API change.** Both already carry unlimited depth (above).
- **No change to how foreign orders behave.** The mirror's `current` set comes
  from `TableRead.list_live_order_levels(conn, user.api_key, tokens)`
  (`reconciler.py:172`) — scoped to the house account — so a real user's order is
  never a cancel candidate at any price. Verified live on production: posting a
  user BUY at 0.001, below every mirrored level, took the book from 8 bids to 9
  with that level visible. A depth cap therefore bounds only *synthetic*
  liquidity; user orders always appear, and a user order at a house price simply
  aggregates into the same book level.

## The real cost, and why two tiers

The mirror is event-driven, not a poll-everything loop: `run_reconciler`
(`agentpit/liquidity/mirror.py:164-203`) reconciles only assets in
`state.dirty`, which the feed marks on each upstream book update
(`feed.py:86,93`), throttled per asset by
`mirror_reconcile_min_interval_seconds` (0.5 s).

So depth multiplies cost twice: each pass diffs ~5× more levels, **and** passes
fire more often, because a change at any of ~40 levels marks the market dirty.
Production runs on 2 vCPU. Refreshing deep levels on the hot path is what must
be avoided — which is exactly what the user proposed.

## Design

### 1. Two tiers, split by price distance from the touch

- **Hot pass** — every dirty event, as today. Reconciles only the top
  `mirror_hot_depth` levels per side.
- **Cold pass** — per market, every `mirror_cold_interval_seconds`. Reconciles
  the full depth up to `mirror_book_depth` and prunes deep levels that
  disappeared upstream.

The tiers are split by **price**, not by list index, so that when the touch
moves, levels migrate between tiers on their own. From a snapshot and the hot
depth, derive two cut prices: `bid_cut` = the price of the hot-depth-th bid,
`ask_cut` = the price of the hot-depth-th ask (a side with fewer levels than the
hot depth has no cold region on that side).

Because the NO book is mirrored as the `MICRO - p` complement
(`MICRO = 1_000_000`, `replica.py:10`), the hot test must be expressed per
(token, side):

| placement | derived from | hot when |
|---|---|---|
| YES BUY @ p | bid @ p | `p >= bid_cut` |
| NO SELL @ MICRO−p | bid @ p | `price <= MICRO - bid_cut` |
| YES SELL @ p | ask @ p | `p <= ask_cut` |
| NO BUY @ MICRO−p | ask @ p | `price >= MICRO - ask_cut` |

This lands as one pure function in `reconciler.py` — call it
`is_hot_level(token_id, side, price_micro, cuts, yes_token) -> bool`, plus
`hot_cuts(snap, hot_depth) -> HotCuts` — both trivially unit-testable and with no
DB or chain dependency.

### 2. `diff_levels` must stop cancelling the cold tier

`diff_levels` (`reconciler.py:61-81`) cancels every live order not present in
`desired`. Calling it with only the hot levels would therefore wipe the entire
deep book on the next dirty event — the single biggest regression risk in this
change.

`diff_levels` gains an optional `protect: Callable[[LiveLevel], bool] | None`.
Live orders for which `protect` returns true are neither kept nor cancelled —
they are simply out of scope for that pass. The hot pass passes
`protect=lambda o: not is_hot_level(...)`; the cold pass passes nothing and keeps
today's exact semantics.

### 3. Scheduling, and not stampeding on boot

`run_reconciler` keeps a `last_cold: dict[str, float]` beside its existing
`last_run`. A market's pass is cold when
`now - last_cold[asset] >= mirror_cold_interval_seconds`.

On a fresh process every market would be due at once — 999 markets × ~160
placements in one burst, on 2 vCPU. `last_cold` is therefore seeded at startup
with a deterministic per-asset offset spread across the interval:
`seed = now - (stable_hash(asset) % cold_interval)`, so the first cold sweeps
fan out evenly over the first 30 minutes instead of landing together. The hash
must be stable across processes (`hashlib`, not Python's salted `hash()`).

A cold pass is also a superset of a hot pass, so when a market is due for cold
work the pass runs once, in cold mode, rather than twice.

### 4. Configuration — a no-op until deliberately raised

| setting | default | meaning |
|---|---|---|
| `AGENTPIT_MIRROR_HOT_DEPTH` | 8 | levels per side reconciled on every dirty event |
| `AGENTPIT_MIRROR_BOOK_DEPTH` | 8 | **now the total cap**, converged by the cold sweep |
| `AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS` | 1800 | per-market cold cadence |

Production currently sets `AGENTPIT_MIRROR_BOOK_DEPTH=8`. With hot depth also 8,
the cold region is empty and behaviour is byte-identical to today — the change
ships dark and is switched on by raising that one value in the prod `.env`.

## Testing

- `hot_cuts` / `is_hot_level`: hot and cold classification on both tokens and
  both sides, including the NO complement; a side shallower than the hot depth;
  and a level that flips tiers when the touch moves.
- `diff_levels` with `protect`: protected live orders are neither cancelled nor
  counted as kept; unprotected behaviour is unchanged (existing tests must pass
  untouched).
- **The regression guard:** a hot pass over a market whose deep levels are
  already live cancels nothing beyond the hot band.
- Cold scheduling: a market is cold-due only after the interval; the startup
  seed spreads first-sweep times across the interval rather than clustering.
- The existing reconciler suite must stay green — it encodes the crossing /
  settlement-budget rules this change does not touch.

## Out of scope

- Bounding the hot pass's DB read by price (it still reads all house levels for
  the market and partitions in Python). Measure first; optimise only if the read
  shows up.
- Any change to crossing classification, settlement budgets, or inventory.
- UI, API, and frontend work of any kind.

## Rollout

The code ships inert: production's `.env` sets `AGENTPIT_MIRROR_BOOK_DEPTH=8`
and the new `AGENTPIT_MIRROR_HOT_DEPTH` defaults to 8, so the cold band is
empty and every pass is the legacy full reconcile.

To enable, raise the cap in the production `.env` to
`AGENTPIT_MIRROR_BOOK_DEPTH=50` and restart the api container. Expect the
deep book to fill in gradually over the first `AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS`
(30 min) rather than at once — the sweeps are staggered per market by design.
That "fills in gradually" describes the steady-state population, not every
individual market — see the cold-sweep caveat below.

**The live-order count is a floor, not a ceiling.** A hot pass never cancels
a cold-classified order, so levels the touch walks past accumulate until
that market's next sweep — `mirror_book_depth` is the depth the cold sweep
converges *toward*, not a cap on live orders between sweeps. Measured on a
drifting 40x40 book with hot 8 / cap 50 over one sweep interval: **116** live
orders at 1 tick of drift per pass, **268** at 3 ticks, **980** at 10 ticks —
all well past the `4 x cap = 200` naive ceiling. Hot-path cost tracks this
accumulated live set, not `mirror_hot_depth`, since `reconcile_market` reads
all house levels for the market on every hot pass.

**The cold sweep is a permission gate on dirty events, not an independent
timer.** `run_reconciler` only considers assets in `state.dirty`, so a market
with no upstream book updates never gets a cold pass: a quiet market never
converges to the deep book, and one that goes quiet keeps whatever deep
levels it already placed until it updates again. This matters most for the
deliberately short-lived rotating-series markets (~5 min windows): with a
uniform startup offset spread over the full 1800 s cold interval, only about
one in six of them reaches its first sweep before expiring.

Watch during the first hour, on a 2 vCPU host:
- `docker stats` for the api container's CPU,
- `SELECT count(*) FROM orders WHERE STATUS = 'live'` — expect roughly 5x
  today's ~35k as depth converges toward 50 levels, and more than that on
  fast-moving markets between sweeps (see above),
- `df -h /` and the json log sizes, since more placements mean more log lines.

To roll back, set the cap to 8 and restart: the next cold sweep per market
prunes the deep levels back out, since a cold pass protects nothing.
