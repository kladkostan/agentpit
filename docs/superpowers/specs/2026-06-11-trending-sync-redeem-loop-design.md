# Trending sync + decoupled resolution/auto-redeem loop — design spec

**Date:** 2026-06-11
**Status:** Approved (pending implementation plan)
**Area:** `agentpit/polymarket/`, `agentpit/api/app.py`, `agentpit/config.py`, `agentpit/db/`

## 1. Overview

Four related changes to how agentpit ingests Polymarket markets and propagates
their resolutions to the local CTF:

1. **Trending universe** — broaden the synced market set to the top-N markets by
   24-hour volume (the practical "trending" set), so high-velocity markets like
   *BTC Up or Down 5m* are included.
2. **Cheap sync** — make a re-sync pass over already-known markets do no on-chain
   work, so the sync loop can run at a high cadence without load.
3. **Decoupled resolution-mirror loop** — move upstream→local resolution
   mirroring out of the market-discovery sync into its own lifespan loop with its
   own interval, and make it scan only candidate (ended, unresolved) markets.
4. **Auto-redeem** — after a market is resolved on-chain, the loop redeems all
   token holders automatically (custodial keys are server-held), so no bot/user
   action is needed to convert resolved positions to apUSD.

### Motivation

- The bulk fetch hard-filters on `liquidity_threshold = 1_000_000` and never
  surfaces short-lived high-frequency markets (a single 5-minute BTC window does
  not clear $1M liquidity in its window), so they can't be traded locally.
- Every sync pass re-runs `prepare_market_on_chain` (≈6 on-chain read calls per
  market) for **already-synced** markets, because the existence check happens
  *after* the on-chain prepare. At a 5-minute cadence over hundreds of markets
  this is heavy and entirely wasteful.
- Resolution mirroring is bundled inside the discovery sync
  (`fetch_and_sync_polymarket_markets`), so redeem-readiness cannot be checked on
  its own cadence, and it polls upstream for *every* unresolved market each pass.
- Redeem is currently manual-only: the loop reports payouts on-chain and flips
  the row to `RESOLVED`, but a holder must call `POST /markets/{id}/redeem_position`
  themselves to actually collect.

## 2. Goals / Non-goals

### Goals
- Include top-N-by-24h-volume markets (config-bounded) in the local sync set.
- A re-sync over already-known markets performs DB reads only — no on-chain calls.
- Resolution mirroring runs as an independent loop on its own interval and only
  inspects candidate markets.
- Resolved markets are auto-redeemed for all holders (including the house
  account), idempotently, without manual action.

### Non-goals
- No changes to the liquidity-mirror engine (`agentpit/liquidity/`).
- No new HTTP API endpoints; no WebSocket streams.
- No change to the order-matching, balance, or position-read surfaces.
- Multi-outcome (non-binary) markets remain out of scope (the local CTF prepare
  path supports binary only).

## 3. Current state (verified)

- `fetch_all_polymarket_markets` (`agentpit/polymarket/polymarket_sync.py:178`)
  paginates Gamma `/markets?active=true&closed=false&archived=false` and drops any
  market with `max(liquidity, volumeNum) < liquidity_threshold` (default
  `1_000_000`, line 247).
- `create_polygon_market_if_does_not_exist` (`polymarket_sync.py:526`) calls
  `prepare_market_on_chain` (line 538, on-chain `getConditionId` /
  `getOutcomeSlotCount` / token-id derivation, and `prepareCondition` +
  `registerToken` only when not yet prepared) **before** the existence check
  `read_condition_id_by_polymarket_id` (line 544). Already-synced markets pay the
  on-chain read cost every pass and then only rebind their event.
- A cheap existence helper already exists:
  `TableRead.market_exists_by_polymarket_id` (`agentpit/db/table_read.py:64`).
- `fetch_and_sync_polymarket_markets` (`polymarket_sync.py:477`) runs market
  creation and then calls `mirror_polymarket_resolutions` (line 486) in the same
  pass. It is driven by `_polymarket_sync_loop` / `_run_polymarket_sync`
  (`agentpit/api/app.py:59,65`) which starts in the lifespan only when
  `settings.sync_enabled` (`config.py:24`, default `False`; `.env.example` sets
  `SYNC=true`). Interval = `sync_interval_seconds` (default 3600).
- `mirror_polymarket_resolutions` (`polymarket_sync.py:592`) walks
  `TableRead.list_all_markets`, skips `RESOLVED`/`CANCELLED`, fetches upstream via
  `_default_resolution_fetcher` (CLOB `/markets/{polymarket_condition_id}`),
  detects the winner via `_winner_index_if_resolved` (`closed == true` + a token
  with `winner == true`), calls `admin.report_payouts(keccak(question), payouts)`
  on the local CTF (idempotent via `payoutDenominator` precheck), and flips the
  row to `RESOLVED`.
- `PositionService.redeem` (`agentpit/services/position_service.py:69`) requires
  `market_state == RESOLVED`, then calls
  `redeemPositions(apUSD, 0x0, condition_id, partition)` signed with the user's
  custodial `eth_key` via `send_user_tx`. Winning outcome token → apUSD, losing
  token → 0. There is no auto-redeem; the route
  `POST /markets/{market_id}/redeem_position` (`agentpit/api/routes/positions.py:34`)
  is the only trigger today.

## 4. Change 1 — Trending universe (top-N by 24h volume)

Replace the bulk "fetch everything, filter by a fixed liquidity floor" with a
Gamma query ordered by 24-hour volume and capped to a configurable top-N.

- Query Gamma `/markets` with `order=volume_24hr` + `ascending=false` +
  `active=true` + `closed=false` (+ `archived=false`), taking the first
  `SYNC_MAX_MARKETS` rows.
- The liquidity/volume floor becomes configurable and defaults low
  (`SYNC_LIQUIDITY_MIN = 0`), so it no longer silently excludes high-velocity
  markets. The top-N-by-volume ordering provides the relevance previously sought
  by the floor.
- Binary-only still enforced downstream: non-binary markets fail
  `prepare_market_on_chain` and are skipped per the existing
  `create_polymarket_markets_if_needed` try/except.
- Side benefit: fetching an ordered top-N is one-to-a-few pages instead of
  paginating all markets, so the fetch itself is cheaper.

**Open item (resolve at implementation against the live Gamma OpenAPI):** the exact
ordering parameter spelling — `order=volume_24hr` vs `order=volume24hr` (the
response field is `volume24hr`). Confirmed via polymarket-docs that ordering by
24h volume, `ascending`, and `volume_num_min`/`liquidity_num_min` filters exist;
the exact key will be verified empirically.

### New config
| env | default | meaning |
|---|---|---|
| `SYNC_MAX_MARKETS` | `300` | Top-N markets (by 24h volume) to sync each pass |
| `SYNC_LIQUIDITY_MIN` | `0` | Minimum `max(liquidity, volume)` floor; `0` = no floor |

## 5. Change 2 — Cheap sync (skip on-chain for known markets)

Reorder `create_polygon_market_if_does_not_exist` so the existence check runs
first:

1. Build the create-request and read `polymarket_id`.
2. `TableRead.market_exists_by_polymarket_id(db, polymarket_id)`.
3. **If it exists:** skip `prepare_market_on_chain` entirely (no on-chain calls);
   do the existing cheap event rebind
   (`bind_existing_market_to_upstream_event`) and return `None`.
4. **If new:** run `prepare_market_on_chain` (prepareCondition + registerToken +
   token derivation), create the row, bind to the upstream event.

Result: a re-sync over N markets where most already exist performs only DB reads
(+ a cheap event rebind), making a high-cadence sync safe.
`SYNC_INTERVAL_SECONDS` keeps its current default (3600) and remains
configurable.

## 6. Change 3 — Decoupled resolution-mirror loop

- Remove the `mirror_polymarket_resolutions` call from
  `fetch_and_sync_polymarket_markets` (`polymarket_sync.py:486`).
- Add a new lifespan loop `_resolution_mirror_loop` in `agentpit/api/app.py`,
  started when `RESOLUTION_MIRROR_ENABLED`, on its own
  `RESOLUTION_MIRROR_INTERVAL_SECONDS` interval, mirroring the existing
  `_polymarket_sync_loop` structure (`asyncio.to_thread`, cancellation handling,
  exception logging).
- Make the mirror cheap: it inspects only **candidate** markets — not
  `RESOLVED`/`CANCELLED` and with `end_date` already in the past — via a new
  `TableRead.list_unresolved_ended_markets(db, now)`. This bounds upstream CLOB
  fetches to markets that could plausibly be resolved, instead of every
  unresolved market. (BTC 5m markets cross `end_date` every 5 minutes, so they
  become candidates promptly.)
- `mirror_polymarket_resolutions` is refactored to take the candidate list (or to
  call the new candidate query internally) rather than walking
  `list_all_markets`.

### New config
| env | default | meaning |
|---|---|---|
| `RESOLUTION_MIRROR_ENABLED` | = `SYNC` | Enable the resolution/auto-redeem loop |
| `RESOLUTION_MIRROR_INTERVAL_SECONDS` | `300` | Loop interval (5 min) |

## 7. Change 4 — Auto-redeem

A second phase of the resolution loop. After a market is resolved on-chain
(payout vector reported, row `RESOLVED`), redeem all holders automatically.

### Flow per pass
For each `RESOLVED` market whose `FULLY_REDEEMED` flag is not set:

1. **Candidate holders** = accounts that participated in the market: distinct
   `TAKER_API_KEY`/`MAKER_API_KEY` from `trades` whose `ASSET_ID` is one of the
   market's token ids, plus distinct `API_KEY` from `transactions` with
   `MARKET_ID = market_id` (SPLIT/MERGE), plus the liquidity-mirror house
   account. Resolve each to a `User` (api_key → User with custodial `eth_key`).
   This scopes the scan to real participants, not the whole users table.
2. For each candidate: read on-chain `ctf_balance` for both outcome token ids.
3. For any candidate with a nonzero balance: best-effort `admin.fund_gas`
   top-up (in case native gas ran low), then `PositionService.redeem(user,
   market_id)` (which signs `redeemPositions` with the user's custodial key and
   the server broadcasts it). Winning token → apUSD, losing token burns for 0.
4. **Idempotency:** zero-balance candidates are skipped (no tx). When no
   candidate holds a nonzero balance of either token, set
   `markets.FULLY_REDEEMED = true` and stop scanning the market thereafter — this
   bounds the loop as the set of resolved markets grows.
5. **Isolation:** per-holder `try/except` + log; one holder's failure does not
   block the others (same pattern as the resolution mirror).

### Scope decision
Redeem **all** holders with a nonzero balance, **including the house/liquidity-
mirror account**. A `RESOLVED` market is no longer `ACTIVE`, so the mirror
reconciler (which only operates on active synced markets) will not touch it;
redeeming the house's leftover inventory safely returns apUSD to the house.

### New config
| env | default | meaning |
|---|---|---|
| `AUTO_REDEEM_ENABLED` | `true` | Auto-redeem holders of newly-resolved markets |

### Loop order per pass
1. Resolve ended-unresolved candidates → `reportPayouts` + flip `RESOLVED`.
2. Auto-redeem holders of `RESOLVED` markets without `FULLY_REDEEMED`.

## 8. Data model change

Add `FULLY_REDEEMED BOOLEAN NOT NULL DEFAULT FALSE` to the `markets` table
(additive, non-breaking) via `TableCreate`. Set/read it via `TableWrite` /
`TableRead` / `_row_to_market` (and the `Market` datastructure). No existing
column changes.

## 9. Cadence (all configurable)

- Discovery/sync loop: ~1h default (cheap even if lowered, after Change 2).
- Resolution + auto-redeem loop: ~5 min default (cheap — only ended-unresolved
  candidates, then redeem of participant holders).

## 10. Failure modes / edge cases

- **Gamma ordering key unknown:** verified at implementation; fall back to the
  current floor-based fetch if the order param is unavailable.
- **Non-binary market in the trending set:** skipped at creation (existing
  try/except), no crash.
- **Upstream not yet resolved:** mirror skips (no winner marker); market remains
  a candidate next pass.
- **`report_payouts` already reported:** skipped via `payoutDenominator` precheck
  (existing behavior).
- **Holder has no gas:** best-effort `fund_gas` top-up before redeem; on failure,
  log and continue (market not marked `FULLY_REDEEMED`, retried next pass).
- **Re-entrancy / double-redeem:** prevented by the on-chain balance check
  (zero-balance holders are skipped) and the `FULLY_REDEEMED` flag.
- **Market with null `end_date`:** excluded from the ended-candidate query; if
  such markets must resolve, they are handled when a future pass observes a
  CLOSED upstream — out of scope for the cheap candidate filter (documented
  limitation; trending markets carry an `endDate`).

## 11. Testing

- **Unit (no chain):** trending fetch builds the ordered/capped Gamma query;
  `create_polygon_market_if_does_not_exist` performs no on-chain prepare for an
  already-existing `polymarket_id` (assert `prepare_market_on_chain` not called);
  `list_unresolved_ended_markets` returns only non-resolved markets past
  `end_date`.
- **On-chain integration (extend `tests/onchain/test_resolution_mirror.py`):**
  create a synced binary market, split to give a holder both tokens, mirror an
  upstream-resolved response, then run the auto-redeem phase → assert the
  holder's on-chain apUSD balance increased by the winning amount, both token
  balances are 0, and `FULLY_REDEEMED` is set. Second pass is a no-op
  (idempotent).

## 12. Files touched

- `agentpit/polymarket/polymarket_sync.py` — trending fetch + ordering; reorder
  existence check in `create_polygon_market_if_does_not_exist`; refactor
  `mirror_polymarket_resolutions` to candidate list; add the auto-redeem phase
  (or a sibling function the loop calls).
- `agentpit/api/app.py` — new `_resolution_mirror_loop` lifespan task; remove the
  mirror call from the sync path.
- `agentpit/config.py` — `SYNC_MAX_MARKETS`, `SYNC_LIQUIDITY_MIN`,
  `RESOLUTION_MIRROR_ENABLED`, `RESOLUTION_MIRROR_INTERVAL_SECONDS`,
  `AUTO_REDEEM_ENABLED`.
- `agentpit/db/table_read.py` — `list_unresolved_ended_markets`, participant /
  candidate-holder query, `FULLY_REDEEMED` in `_row_to_market`.
- `agentpit/db/table_create.py` / `table_write.py` — `FULLY_REDEEMED` column +
  setter.
- `agentpit/datastructures/market.py` — `fully_redeemed` field.
- `.env.example` — document the new env vars.

## 13. Out of scope / deferred

- Auto-redeem for accounts that never traded/split but somehow hold tokens via
  raw transfer (not produced by agentpit flows).
- Backfill auto-redeem of historically-resolved markets (the candidate query is
  forward-looking; a one-off backfill can be run separately if needed).
- Per-category or tag-based universe selection (only top-N-by-volume in v1).
