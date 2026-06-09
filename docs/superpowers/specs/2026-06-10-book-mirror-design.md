# Book Mirror — Design Spec (Phase 5c)

**Status:** Design, approved 2026-06-10. Supersedes the synthetic-ladder Liquidity Engine
(`2026-06-08-liquidity-engine-design.md`, Stages 1–2) as the activity mechanism.
**Date:** 2026-06-10
**Branch:** `mvp`
**Builds on:** Phase 5a (Postgres) + the existing liquidity engine scaffolding (house
accounts, lifespan wiring, service-layer direct calls), which this design reuses.

---

## 1. Goal

The synthetic U-shape ladder produces a visibly fake book: evenly spaced rungs of
identical size plus fixed walls (`ladder.py` splits `spread_size // near_count` uniformly
with zero jitter). Writing a convincing noise generator is a losing game. Instead:

1. **The local book is a 1:1 replica of the real Polymarket book** — every (price, size)
   level of the real book becomes exactly one resting house-account GTC order locally,
   reconciled continuously from the Polymarket CLOB WebSocket market channel.
2. **The local tape is a mirror of the real Polymarket tape** — every real trade
   (`last_trade_price` event) becomes a synthetic row in `trades`, which also feeds
   `GET /last-trade-price` and the price-history charts (both read `trades` filtered by
   `STATUS != 'FAILED'` — `order_service.py:279,357,407`).

Polymarket is the source of truth; agentpit replays it. Realism is achieved by
construction, not simulation. The ladder, the price oracle peg, and the Stage-2
"arb print" machinery are **deleted**.

## 2. Non-goals

- No change to the trader-facing HTTP API surface (Polymarket-shape-exact stays).
- No real on-chain settlement for mirror activity. Resting orders are signature + DB
  insert only (`order_service.py:56-146` — confirmed: a non-crossing GTC triggers zero
  chain txs); cancels are DB-only `UPDATE`s (`order_service.py:213-216`). Settlement
  remains only for real (trader-bot) fills, as today.
- Stage-3 resolution redeem is still a separate future phase; here we only
  unsubscribe + cancel house orders on the `RESOLVED` edge.
- No order-book mirroring for markets without `POLYMARKET_CONDITION_ID` (nothing to
  mirror; they stay empty as today).

## 3. Verified upstream facts the design is built on

All verified live on 2026-06-09 against `wss://ws-subscriptions-clob.polymarket.com/ws/market`
and `https://clob.polymarket.com`, cross-checked with docs.polymarket.com, py-clob-client,
and the NautilusTrader Polymarket adapter:

1. The **market channel is public** (no auth). Subscribe:
   `{"assets_ids": ["<token_id>", ...], "type": "market"}`. Dynamic
   `{"assets_ids": [...], "operation": "subscribe"|"unsubscribe"}` works on a live
   connection and delivers a fresh `book` snapshot for newly added assets.
2. **`price_change` carries REPLACE semantics**: `size` is the new total at that price
   level; `size == "0"` removes the level. (Docs + NautilusTrader UPDATE/DELETE handling
   + live REST cross-check, three independent confirmations.)
3. A single `price_change` message carries **mirrored entries for both sibling
   asset_ids** of the market, even if only one is subscribed — filter by per-entry
   `asset_id`.
4. **YES and NO books are exact 1−p mirrors** of one unified book (live check: 99/99
   levels matched with identical sizes). Subscribing to the YES token only is sufficient;
   the NO book is derivable.
5. **Undocumented cap ≈500 assets per connection, failing silently** (no initial `book`
   snapshots above it). NautilusTrader caps at 200/connection; we do the same and shard.
6. Keepalive: client sends the **text frame `"PING"` every 10s**. Known failure mode
   ("silent freeze", py-clob-client issue #292): PING/PONG stays healthy while data
   stops for hours → PING/PONG is NOT a liveness signal; an **event-inactivity watchdog**
   is mandatory.
7. Message framing is heterogeneous: a message may be a JSON **array of events or a
   single event object**. Live book arrays are sorted **worst-to-best** (docs example
   shows the opposite) — never trust array order, index by price.
8. `book` event: `{event_type, asset_id, market, bids, asks, timestamp, hash, tick_size,
   last_trade_price}` — all prices/sizes are decimal **strings** (parse via `Decimal`,
   never float). `tick_size_change` invalidates the book epoch: drop the replica and
   re-seed from a fresh snapshot (NautilusTrader pattern).
9. `last_trade_price` event: `{event_type, asset_id, market, price, size, side,
   fee_rate_bps, timestamp}` — emitted per real trade.
10. REST fallback: `GET /book?token_id=` (1,500 req/10s) and batch `POST /books` with
    `[{"token_id": ...}]` (500 req/10s); enforcement is Cloudflare throttling (delays,
    not 429s). REST snapshots can themselves be stale (issue #180) — sanity-check on
    resync.
11. Typical depth (20-market live sample): 8–185 levels/side; one side may be empty;
    sizes at extreme prices reach millions of shares. Tick sizes seen: 0.001 and 0.01 —
    both land on the local 0.001 grid natively.

## 4. Local-engine facts the design is built on

1. `place_order` is fully synchronous; for a **non-crossing GTC** it does: token
   resolution → one on-chain `.call()` balance read (USDC for BUY / CTF for SELL) →
   EIP-712 sign (per-account key, salt-randomized, no cross-account nonce contention) →
   DB insert. No chain tx (`order_service.py:56-146`, `onchain/admin.py:124-135`).
2. Cancels: `DELETE /order` (single), `DELETE /orders` (list), `cancel_market_orders`
   (by market) — all DB-only (`order_service.py:213-265`). No limits on open orders.
3. The matcher considers NORMAL (same token, opposite side) **and MINT/MERGE**
   (complement token, same side) with thresholds `p_taker + p_maker >= 1` (MINT) /
   `<= 1` (MERGE) — boundary **inclusive** (`order_service.py:585-672`).
4. The book read is one `GROUP BY` aggregate per token (`order_service.py:267-316`);
   fine at mirror scale (≲400 house orders/token).
5. Charts and `last-trade-price` read the `trades` table (`STATUS != 'FAILED'`); trades
   has **no FK constraints** (`table_create.py:9-31`); successful trades keep status
   `'PENDING'` — only failures are rewritten to `'FAILED'`.
6. `websockets==12.0` is already in requirements; Python 3.13; no WSS usage yet.
7. Settlement (only for real fills) is a single admin key behind `send_lock`, ≤60s per
   receipt, serialized across all markets.

## 5. The non-crossing invariant (why the mirror can't self-match)

We place BOTH local books: YES levels verbatim, NO levels as the complement
(BUY NO @ 1−ask_p, SELL NO @ 1−bid_p, same sizes). The matcher's MINT/MERGE boundary is
inclusive at sum exactly 1, so the safety argument must be exact:

Let the YES replica be non-crossed: `max_bid < min_ask` (strict, integer micro).
- NO book internal: NO bids max = `1−min_ask` < NO asks min = `1−max_bid` ✓ non-crossed.
- BUY NO @ `1−a` MINT-matches maker BUY YES @ p only if `p >= a`; all YES bids
  `<= max_bid < min_ask <= a` ✗.
- SELL NO @ `1−b` MERGE-matches maker SELL YES @ p only if `p <= b`; all YES asks
  `>= min_ask > max_bid >= b` ✗.
- Symmetrically for YES orders against resting NO complements ✗.

So **while every intermediate state keeps house bids strictly below house asks (per
token, and via the complement map across tokens), no house order can match another
house order** — neither NORMAL nor MINT/MERGE. The reconciler guarantees intermediate
safety by ordering: **all cancels first, then all placements**, per market per cycle.
Polymarket's published book is never crossed (single matching engine), so the target
state is always safe; the cancel-first rule covers the transitions.

Residual guard (belt and braces): before each placement the reconciler compares against
the current local house touch; a placement that would cross a *house* order is skipped
and logged (self-heals next cycle). A placement that crosses a **non-house** order is
intentional — see §7.

## 6. Architecture

```
create_app() lifespan
 ├─ provision house accounts ONCE (unchanged, house_accounts.py)
 ├─ feed_task      = create_task(_mirror_feed_loop(...))        # async WSS client
 ├─ reconcile_task = create_task(_mirror_reconcile_loop(...))   # dirty-market worker
 └─ finally: cancel both alongside sync/snapshot tasks

_mirror_feed_loop          # async; owns N sharded WSS connections (≤200 assets each)
  - initial seed: REST POST /books in batches → BookReplica per market
  - subscribe YES token ids; parse array|object framing; route events:
      book / price_change / tick_size_change → replica.apply → mark market dirty
      last_trade_price → tape queue
  - text "PING" every 10s; watchdog: no events for MIRROR_WATCHDOG_SECONDS →
    reconnect + REST resync (sanity-checked); dynamic subscribe on new synced markets,
    unsubscribe + final cleanup on RESOLVED/CANCELLED edge

_mirror_reconcile_loop     # async; pulls dirty markets, coalesced
  - per market at most once per MIRROR_RECONCILE_MIN_INTERVAL_SECONDS
  - await asyncio.to_thread(reconcile_market, db, admin, market, replica_snapshot)
  - tape writer drains the trade queue (DB-only inserts, same thread budget)
```

Both loops follow the existing sibling-task pattern (`CancelledError` re-raised before
broad `except`, work off the event loop via `to_thread`).

### Components

| Component | Location | Responsibility |
|---|---|---|
| `MirrorFeed` | `agentpit/liquidity/feed.py` (new) | WSS connections, sharding, keepalive, watchdog, REST seed/resync, event routing. Pure-async; no DB. |
| `BookReplica` | `agentpit/liquidity/replica.py` (new) | Pure data: per-market price→size maps (micro ints, from `Decimal(str)`), `apply_book`, `apply_price_change` (replace; 0=delete; filter by asset_id), `apply_tick_size_change` (epoch reset → needs_resync), non-crossed validation, snapshot export. No I/O — unit-testable. |
| `reconcile_market` | `agentpit/liquidity/reconciler.py` (new) | Pure diff + applier: target levels (YES verbatim + NO complement) vs live house orders (one order per (token, side, price) level) → cancel list + place list; cancels before placements; inventory check/top-up; crossing guards (§5, §7). Diff itself is a pure function — unit-testable. |
| `TapeMirror` | `agentpit/liquidity/tape.py` (new) | `last_trade_price` → synthetic `trades` row: `STATUS='MIRRORED'`, price/size/side/`MATCH_TIME` from the event, local `ASSET_ID`/`MARKET` via the token map, synthetic `TRADE_ID`/`TAKER_ORDER_ID`, house-account pair as `TAKER_API_KEY`/`MAKER_API_KEY`, `TRANSACTION_HASH=NULL`. |
| `HouseAccounts` | `agentpit/liquidity/house_accounts.py` (kept) | Unchanged provisioning/re-onboarding. Account↔market assignment: round-robin, one account owns all mirror orders of its market(s). |
| Deleted | `ladder.py`, `price_oracle.py`, engine print/quote logic, their config fields and tests | Replaced by the mirror. The only surviving piece is a REST `/books` fetch helper, which moves into `feed.py` (seed + resync). |

### Token/ID mapping

Fetch with `POLYMARKET_YES_TOKEN_ID` (subscription key), quote with local
`erc1155_tokens[0][0]` (YES) / `[1][0]` (NO), tape rows use local ids; market scoping by
local `CONDITION_ID`, peggability by `POLYMARKET_CONDITION_ID IS NOT NULL` — same
two-namespace rule as before. The feed maintains `polymarket_yes_token_id → (market,
local_yes, local_no)`.

## 7. Interaction with real (trader-bot) orders

- A bot **taker** order crossing mirror orders fills exactly as today: synchronous
  matching + on-chain settlement inside the bot's HTTP request. The consumed mirror
  levels are restored by the next reconcile (the book "refills", like real MM behavior).
- A bot **resting** order inside the spread: when the real market moves through its
  price, the reconciler's new placement legitimately crosses it — this is a desired
  fill (the bot would have been filled on the real venue too). Such placements run via
  the normal `place_order` path (real matching + settlement), are executed **after** the
  DB-only batch, and are capped at `MIRROR_MAX_SETTLEMENTS_PER_CYCLE` per cycle so one
  slow settlement (≤60s, global admin lock) cannot stall mirroring; remaining crossing
  placements defer to later cycles. `OrderResponse.success` is inspected (settlement
  failure does not raise).
- Failed-settlement residue (`FAILED` trades) is already filtered by all readers.

## 8. Inventory

SELL orders require on-chain CTF inventory (per-order `.call()` check). A split mints
YES and NO equally, and the NO ask side is the complement of the YES bid side, so the
split target per market is `max(Σ YES-ask sizes, Σ NO-ask sizes) ×
MIRROR_INVENTORY_BUFFER` (default 1.2) — one split top-up covers both books.
Top-ups are admin txs behind `send_lock`: budget `MIRROR_MAX_SPLITS_PER_CYCLE` (default 2)
per reconcile cycle. While inventory lags the target, ask levels are placed
best-price-first until inventory runs out and the market is flagged "catching up" —
the book converges over a few cycles. Real books hold millions of shares at extreme
prices; with $1B apUSD per account this is ample ($1B ≈ 1e9 shares split budget), but
per-market split sizing must use BIGINT-safe micro math (Phase-5a audit applies).
BUY-side needs only USDC; $1B covers any realistic bid wall.

## 9. Tape mirror details

- Insert via a single new `TableWrite`-style function (one INSERT, schema-compatible with
  `table_create.py:9-31`); no FK constraints exist; `STATUS='MIRRORED'` is distinct for
  provenance yet passes every `!= 'FAILED'` filter (last-trade-price, price history,
  midpoint fallbacks).
- Charts immediately gain real Polymarket price history going forward (they read trades).
- Both sibling events may arrive for one real trade (YES and NO views). V1 policy: write
  the event for the **YES** asset_id only (we subscribe to YES; if NO-side events still
  arrive, drop them) — one row per real trade, attributed to the YES token. Whether
  NO-side `last_trade_price` events arrive on a YES-only subscription is unverified —
  the first implementation task includes a live capture to pin this down (non-blocking
  either way).
- `MIRROR_TAPE_ENABLED` gates the writer independently of the book mirror.

## 10. Configuration (pydantic-settings, explicit `validation_alias`, no prefix)

Removed: `liquidity_ladder_rungs_per_side`, `liquidity_wall_fraction`,
`liquidity_requote_threshold_micro`, `liquidity_makers_per_market`,
`liquidity_taker_pool_size`, `liquidity_print_threshold_micro`,
`liquidity_print_size_shares`, `liquidity_max_prints_per_tick`,
`liquidity_split_per_market_usdc` (split size now derived from the replica).

Kept: `liquidity_engine_enabled` (`LIQUIDITY_ENGINE`, master switch),
`liquidity_house_account_count`, `liquidity_funding_drips`,
`liquidity_interval_seconds` (reused as the reconcile loop idle poll).

Added (defaults):
```python
mirror_assets_per_connection:        int   = 200    # AGENTPIT_MIRROR_ASSETS_PER_CONNECTION
mirror_reconcile_min_interval_secs:  float = 0.5    # AGENTPIT_MIRROR_RECONCILE_MIN_INTERVAL_SECONDS
mirror_watchdog_seconds:             float = 120.0  # AGENTPIT_MIRROR_WATCHDOG_SECONDS
mirror_inventory_buffer:             float = 1.2    # AGENTPIT_MIRROR_INVENTORY_BUFFER
mirror_max_splits_per_cycle:         int   = 2      # AGENTPIT_MIRROR_MAX_SPLITS_PER_CYCLE
mirror_max_settlements_per_cycle:    int   = 1      # AGENTPIT_MIRROR_MAX_SETTLEMENTS_PER_CYCLE
mirror_tape_enabled:                 bool  = True   # AGENTPIT_MIRROR_TAPE_ENABLED
```

## 11. Degradation modes

| Failure | Behavior |
|---|---|
| WSS disconnect / silent freeze | Watchdog (no events ≥120s) → reconnect; re-subscribe yields fresh `book` snapshots (the resync point); REST `/books` as backstop, sanity-checked against the event stream's last `best_bid/best_ask` (stale-snapshot defense). |
| Polymarket fully unreachable | Replicas freeze; resting book stays at last state; tape silent. Acceptable — the rig keeps a plausible static book. |
| Crossed/locked upstream data | `BookReplica` validates non-crossed before export; a crossed replica is discarded and resynced (never reconciled into orders). |
| One-sided/empty book | Mirror whatever side exists; empty side stays empty (matches reality). |
| `tick_size_change` | Epoch reset: drop replica, force resync, reconcile after fresh snapshot. |
| Anvil wipe | Existing re-onboard path (zero native balance → re-fund/re-approve); plus approvals re-grant noted as a known gap to close while touching `_maybe_reonboard`. |

## 12. Testing

- **Pure unit — replica**: apply book/price_change (replace semantics, size 0, sibling
  asset_id filtering, string-Decimal parsing), tick_size_change epoch, worst-to-best
  input order handling, non-crossed validation.
- **Pure unit — diff**: replica + current orders → minimal op set; cancel-before-place
  ordering; NO-complement mapping (prices, sizes); intermediate non-crossing invariant
  across the op sequence; idempotency (unchanged replica → zero ops); inventory-capped
  partial placement (best prices first).
- **Integration (real PG + Anvil, stubbed feed)** — patterns from
  `tests/onchain/test_liquidity_*`: canned event sequence → local `GET /book` equals the
  replica for BOTH tokens; trade event → `MIRRORED` row + `last-trade-price` +
  price-history reflect it; bot resting order inside the spread → real fill when the
  replica moves through it (settlement path, `success=True`, level restored next cycle);
  zero house-vs-house trades ever (assert no trades between house API keys); restart
  idempotency (re-seed produces zero ops on an already-mirrored book).
- **Live smoke (manual/CI-optional)**: 60s against the real WSS with 2 markets — replica
  hash spot-check vs REST, and capture whether NO-side `last_trade_price` arrives (§9).

## 13. Known accepted trade-offs & open items

1. **Effective depth ×2**: one real liquidity pool is expressed twice locally (YES orders
   + NO complements), and the inclusive MINT/MERGE boundary lets a taker tap both at the
   touch. A taker bot sees up to double the real consumable size. Accepted for a test
   rig; revisit only if bot calibration needs exact impact costs.
2. **No order-level identity**: the real book aggregates many makers per level; we place
   one order per level. Invisible through the book API (aggregated by price), visible
   only in house-account order lists. Accepted.
3. **NO-side `last_trade_price` on YES-only subscription** — pinned by live capture in
   the first implementation task (§9).
4. **Public tape endpoint**: `GET /data/trades` is API-key-scoped; if the UI gains a
   public activity feed later, `MIRRORED` rows are already shaped for it. Check what the
   UI event page actually reads when wiring tests (non-blocking).
5. **Scale ceiling**: synced-market count is governed by the existing $1M
   liquidity/volume sync filter; sharding handles WSS fan-out (200/connection, ~6
   connections known-safe). If the synced set grows into many hundreds, revisit
   per-IP connection headroom.
