# Liquidity Engine — Design Spec (Phase 5b)

**Status:** Design. Supersedes the original Phase 5 ("port external `agentpit_bots` onto the new API").
**Date:** 2026-06-08
**Branch:** `mvp`
**Builds on:** Phase 5a (SQLite→Postgres) — DONE + green (264 tests). The engine relies on the psycopg connection pool removing the single-writer bottleneck.

---

## 1. Goal

agentpit is a paper-trading **test rig** for the `agentpit-trader` LLM bot; its HTTP API is a Polymarket-exact clone. Right now agentpit's markets are **empty** — no book, no activity. We need:

1. **Realistic fake activity** — a deep, churning order book on every active synced market, so the trader bot sees a believable market.
2. **Price pegging** — agentpit's prices track the **real Polymarket** mid for the same market.

We build this as an **in-process Liquidity Engine**: a server-side background loop (a third sibling of the existing `polymarket_sync` and `snapshot` loops) that owns ~100 "house" accounts and calls the **service layer directly** (no HTTP/JWT). This dissolves the original Phase-5 blocker (an external HTTP bot can't see the Polymarket↔local token mapping) — a server-side engine reads it straight from the DB, so the trader-facing API stays strictly Polymarket-exact.

## 2. Non-goals

- Not a real matching engine or real money. The chain is local Anvil; collateral is fake `apUSD`.
- Not changing the trader-facing HTTP API surface at all. The engine is invisible to the bot except through normal book/price/trade data.
- Not solving on-chain settlement throughput in this phase (see §6, the single-admin-lock ceiling). We design **around** it.

## 3. Two token-id namespaces (the load-bearing fact)

Every synced market carries **two disjoint** id sets. Getting these crossed produces silent empty books / 404s.

| Use | Columns | Where used |
|---|---|---|
| **Read the real Polymarket mid** | `POLYMARKET_CONDITION_ID`, `POLYMARKET_YES_TOKEN_ID`, `POLYMARKET_NO_TOKEN_ID` | Polymarket CLOB API |
| **Quote / trade locally** | `CONDITION_ID`, `ERC1155_TOKENS` (JSON `[[local_token_id, label], …]`, index 0 = YES, 1 = NO) | agentpit `orders` book, matcher, on-chain CTF |

`create_polygon_market_if_does_not_exist` deliberately overrides upstream condition/token ids with locally-derived ones; only the `POLYMARKET_*` columns remain as the cross-reference. **Fetch with the Polymarket id; quote with the local id.** A market is *peggable* iff `POLYMARKET_CONDITION_ID IS NOT NULL` (the resolution mirror uses the same rule).

All synced markets are **binary** (`prepare_market_on_chain` rejects `outcome_count != 2`), so `erc1155_tokens` always has exactly 2 entries. Prices/amounts everywhere are **micro units** (`1e6` = $1.00 = 1 share); price space is `0 … 1_000_000` micro-USDC/share, snapped to a `0.001` (0.1¢) tick.

## 4. Architecture

A third asyncio task in the FastAPI `lifespan`, mirroring `_polymarket_sync_loop` exactly:

```
create_app()                          # builds singletons: db_session (pool), onchain_admin
 └─ lifespan
     ├─ provision house accounts ONCE at startup (idempotent)   # before the loop
     ├─ engine_task = create_task(_liquidity_engine_loop(db_session, onchain_admin, cfg…))
     └─ finally: cancel engine_task alongside sync_task, snapshot_task

_liquidity_engine_loop(db, admin, interval, cfg)   # async: while True
     try: await asyncio.to_thread(_run_liquidity_tick, db, admin, cfg)   # blocking work off the event loop
     except asyncio.CancelledError: raise            # MUST precede broad except
     except Exception: log.exception(...)
     await asyncio.sleep(interval)

_run_liquidity_tick(db, admin, cfg)    # SYNCHRONOUS, blocking; the real work
     engine = LiquidityEngine(db, admin, cfg)
     return engine.tick()
```

**Service-layer, direct calls.** The engine constructs `OrderService(db, onchain)`, `PositionService(db, onchain)` and uses `TableRead`/`TableWrite`/`OnchainAdmin` with the **same** `db_session`/`onchain_admin` singletons the app builds. House accounts are loaded as full `User` objects (carrying a live `eth_key: LocalAccount`) via `TableRead.get_user_by_*` / a new `list_bot_users`. **No** `dependency_overrides`, no HTTP, no JWT.

**Why `asyncio.to_thread` is mandatory:** the workers are blocking (psycopg + httpx + web3). Running them on the event loop would stall all HTTP request handling.

## 5. Components

New module package: `agentpit/liquidity/` (engine logic), plus small additions to existing modules.

| Component | Location | Responsibility |
|---|---|---|
| `LiquidityEngine` | `agentpit/liquidity/engine.py` (new) | Orchestrates a tick: enumerate target markets → peg → (re)quote ladder → [Stage 2: walk price] → [Stage 3: resolution]. Holds per-market state (last-pegged mid, which accounts quote which market). |
| `HouseAccounts` provisioner | `agentpit/liquidity/house_accounts.py` (new) | Idempotent create + onboard + fund + mark-bot of N house accounts; re-onboard-on-chain-wipe; loads them as `User`s. |
| Polymarket price oracle | `agentpit/liquidity/price_oracle.py` (new) | Fetches the real Polymarket touch — best **bid/ask** via CLOB `/price` (both sides) or `/book` (Stage 1.5), with `/midpoint` as fallback; converts to micro-USDC; per-market try/except. |
| Ladder / distribution | `agentpit/liquidity/ladder.py` (new) | Pure functions: sample the U-shaped/bimodal price+size distribution → a list of `(side, price, size)` rungs around a pegged mid. Easily unit-tested. |
| `TableRead.list_bot_users` | `agentpit/db/table_read.py` (add) | `SELECT {_USER_COLS} FROM users WHERE IS_BOT = 1` → `[User]`. Required for idempotent restart + enumerating house accounts. |
| `TableRead.list_active_synced_markets` | `agentpit/db/table_read.py` (add) | The ACTIVE + `polymarket_condition_id IS NOT NULL` target set (one shared definition the snapshot loop can adopt too). |
| Faucet $1B grant | `scripts/deploy_exchange.sh` (redeploy) | Raise the faucet drip grant to $1B (`SIGNUP_GRANT_RAW=1e15`, now the default; chain redeployed) so house funding = 1 `faucet_drip`. The apUSD `mint`/`setMinter` are `onlyMinter` and the **faucet** is the minter — the admin cannot mint directly, so a `mint_usd` helper is impossible. |
| Loop wiring + Settings | `agentpit/api/app.py`, `agentpit/config.py` | The sibling task + new config fields. |

### Key existing interfaces the engine calls (from recon, exact)

- `OrderService(db, onchain)` → `place_order(user: User, payload: PlaceOrderRequest) -> OrderResponse`. `PlaceOrderRequest(token_id=<LOCAL erc1155 token id str>, side='BUY'|'SELL', price=Decimal(0<p<1, 0.001 tick), size=Decimal(>=1e-6 whole shares), order_type='GTC')`. **Resting (non-crossing) orders cost no chain tx** — just a signature + DB insert. `place_order` signs internally (needs only `user.eth_key`).
- `OrderService.cancel_market_orders(user, market=condition_id, asset_id=None)` — per-account cancel by market (DB-only). Loop over the accounts that quoted the market.
- `OrderService.get_book(token_id)` / `_best_bid_ask(token_id)` — read agentpit's current local touch to keep quotes non-marketable and (Stage 2) decide the walk direction.
- `PositionService(db, onchain)` → `split(user, market_id, SplitPositionRequest(amount_micro))`, `merge(...)`, `redeem(user, market_id)` (requires `RESOLVED`). Or lower-level `OnchainAdmin.user_split_position(user.eth_key, condition_id_bytes, amount)`.
- `OnchainAdmin`: `fund_gas(addr, wei)`, `faucet_drip(addr)`, `mint_usd(addr, raw)` (new), `grant_user_approvals(acct)`, `usd_balance(addr)`, `native_balance(addr)`, `ctf_balance(addr, token_id_int)`.
- `TableWrite.create_user(db, email, password_hash, handle) -> (user_id, LocalAccount, api_key)` (does **not** set IS_BOT), `mark_user_onboarded(user_id)`, `mark_user_as_bot(api_key)`. `TableRead.get_user_by_email`, `_row_to_user`.
- `TableRead.list_all_markets(db)` / `get_market_status_by_condition_id(condition_id)` — enumeration + cheap resolution edge-detect.

## 6. Hard constraints the design must respect

1. **Self-trade guard.** The matcher excludes only the **same `ORDER_ID`**, never the same account. The engine must guarantee taker-account ≠ maker-account when it prints a trade, AND keep its Stage-1 resting quotes strictly non-crossing (bids `< mid <` asks) so nothing matches accidentally.
2. **Settlement ceiling.** A crossing trade → `CTFExchange.matchOrders` as a **single admin key behind one `send_lock`** with up to ~60s/receipt. Real fills are therefore rare and serialized across all markets. Resting/cancel are free. → "Activity" = a deep churning resting book; real trades are a small throttled trickle (Stage 2). *(Confirmed default; revisit before Stage 2 if more fills are wanted.)*
3. **Anvil wipes on restart; Postgres persists.** `ONBOARDED_AT` set in the DB does **not** mean the chain knows the account. Gate trading on `native_balance`/`usd_balance`, not on `ONBOARDED_AT`. Re-onboard (re-fund gas + re-mint + re-approve) when `native_balance == 0`. Mirror `AuthService._maybe_reonboard`.
4. **`place_order` settlement-failure path** leaves the book mutated but trades `FAILED`, returns `success=False` (does not raise). Stage 2 must inspect `OrderResponse.success`, not assume an exception.
5. **No `dict(row)`** on CI rows (lower-cases keys). All DB access via `DbSession.read()/.write()`.

## 7. Order placement distribution (the U-shape)

Measured from real Polymarket books (per the project memory). Per side, asymmetric and bimodal:

- **BUY** size ≈ **42% at 0–5¢** (lowball "buy cheap") + ~19% near the spread.
- **SELL** size ≈ **38% at 95–100¢** ("sell dear") + ~20% near the spread.
- **~70% of resting size sits >10¢ from the touch** (the book accumulates instead of instantly matching).

Engine samples each rung's price from a mixture: ≈ **0.6 "wall"** (near 0/1) + ≈ **0.4 near-spread**, with the near-spread rungs anchored to the pegged Polymarket mid (Stage 1) and then to Polymarket's real best bid/ask (Stage 1.5). Near-spread rungs are placed with a guaranteed gap to the opposite touch so Stage-1 quotes never cross. (Trades, Stage 2, come only from the near-spread part.) Implemented as pure functions in `ladder.py` so the shape is unit-testable in isolation.

## 8. Staged delivery (MVP-first, per decision)

### Stage 1 — MVP: provisioning + price-peg + resting U-shape ladder *(this phase's plan)*
Deliverables:
1. **Config** — new `Settings` fields (§9).
2. **House accounts** — idempotent provision of N accounts: detect existing via `IS_BOT=1` (new `list_bot_users`) + deterministic email `house-bot-{i}@agentpit.local`; create only the shortfall; fund via `faucet_drip` × `liquidity_funding_drips` (1 drip = $1B) + `fund_gas` + `grant_user_approvals` + `mark_user_as_bot` + `mark_user_onboarded`; **re-onboard** any account whose on-chain `native_balance == 0`. Bound the provisioning fan-out (admin txns serialize; ~hundreds of txns at first boot → budget minutes).
3. **Price oracle** — fetch the real Polymarket mid per market (`/midpoint?token_id=POLYMARKET_YES_TOKEN_ID`; batch `/midpoints`), convert to micro, per-market try/except so one illiquid market can't kill the tick.
4. **Target set** — `list_active_synced_markets` (ACTIVE + `polymarket_condition_id` not null; optionally skip past-`END_DATE`).
5. **Inventory bootstrap** — per (account, market) that will quote: ensure split inventory (default **10K** apUSD → 10K YES + 10K NO) so ask-side can rest; skip if `ctf_balance` already ≥ target. Cap total split per wallet at ~½ its balance (rest stays USDC for bids).
6. **Resting ladder** — per active market, a rotating subset of maker accounts each rest a U-shaped GTC ladder pegged to the Polymarket mid, **strictly non-marketable** (bids `< mid <` asks, near-spread rungs gapped from the opposite touch). Re-quote when the pegged mid moves beyond a threshold: `cancel_market_orders` then re-place.
7. **Loop wiring** — `_run_liquidity_tick` + `_liquidity_engine_loop` sibling task, gated on the enable flag, cancelled in the `finally` tuple.

**Stage 1 explicitly produces ZERO real fills** (all quotes non-crossing) → no settlement, no self-trade risk yet.
**Verification:** with the engine on, an empty synced market shows a deep two-sided book whose mid tracks the live Polymarket mid; restart re-detects accounts (no dupes) and re-onboards after an Anvil wipe.

### Pegging model (refined — agreed 2026-06-09)
**Separate "alignment" (what the bot reads) from "activity" (the tape).** The **price oracle is the backbone** of alignment, NOT arbitrage: it's cheap, instant, and exact, and it can't be made hostage to the on-chain settlement bottleneck. Full cross-venue arbitrage is rejected as the *primary* mechanism because agentpit is the only tradeable venue (Polymarket is a read-only fair-value reference, so it's one-sided), and aligning via trades would make price fidelity throughput-bound. We keep the arbitrage *idea* only as the rule that drives the **tape** (Stage 2 prints), where it gives directionally-correct activity for free. Full arbitrage would only be worth it with a second tradeable venue or cheap settlement.

- **Executable-price pegging (not mid).** A taker buys at the best ask and sells at the best bid — the mid is only a reference. So the oracle anchors agentpit's **touch to Polymarket's real best bid/ask** (`/price?token_id&side=buy` → ask, `&side=sell` → bid; or one `/book`), not just `/midpoint`. Then agentpit's best ask ≈ Polymarket's best ask and best bid ≈ Polymarket's best bid → the bot's executable prices and the spread match. The U-shaped walls/depth beyond the touch stay ours (Polymarket-exact depth isn't needed).

### Stage 1.5 — peg the touch to Polymarket's executable bid/ask *(quick patch, keeps ZERO trades)*
Refine the oracle + ladder so the resting touch sits on Polymarket's real bid/ask instead of `mid ± synthetic spread`:
1. `price_oracle.fetch_bid_ask_micro(token_id)` → `(bid_micro, ask_micro)` from Polymarket CLOB `/price` (both sides) or `/book`; per-side `None` on missing/one-sided book; keep a mid fallback.
2. `build_ladder` re-anchored from `(mid)` to explicit `(bid_anchor_micro, ask_anchor_micro)`: bids descend from `bid_anchor`, asks ascend from `ask_anchor`, walls unchanged; still strictly non-crossing (requires `bid_anchor < ask_anchor`; fall back to mid±tick if Polymarket's book is locked/crossed).
3. Engine computes anchors = Polymarket bid/ask, **clamped against agentpit's own touch** (`engine_bid ≤ own_ask − tick`, `engine_ask ≥ own_bid + tick`) so it still never crosses a real-user order. Still **ZERO trades** (resting only). Verify: agentpit best_bid/ask ≈ stubbed Polymarket bid/ask; no `trades` rows.

### Stage 2 — arbitrage-flavoured directional prints (the tape) *(next plan, after Stage 1.5 green)*
The oracle already keeps the **quoted** book aligned. Stage 2 animates the **tape** and corrects the **traded** (last-trade) price using the arbitrage rule, throttled hard against the single-admin-lock budget:
```
F_bid, F_ask = Polymarket best bid/ask     # fair executable prices
if agentpit.best_ask < F_bid:   a taker BUYs agentpit's ask   → price up toward fair
if agentpit.best_bid > F_ask:   a taker SELLs into agentpit's bid → price down toward fair
size = small (1-2 levels); taker account ≠ every maker it crosses (matcher excludes only same ORDER_ID);
inspect OrderResponse.success (settlement failure does NOT raise) and reconcile; cap trades/tick.
```
Taker bots "profit" (buy below / sell above Polymarket fair value), so they're self-sustaining in fake apUSD rather than bleeding capital. Fill rate is a user decision (tape liveness vs tx budget) — confirm before building.

### Stage 3 — resolution cancel + redeem *(final plan, after Stage 2 green)*
Poll `market_state` each tick (no event bus exists); on the unresolved→`RESOLVED` edge, **latch once** per market: (a) `cancel_market_orders` for every house account that quoted it, then (b) for each account with `ctf_balance(winning_token) > 0`, `PositionService.redeem(user, market_id)`. `report_payouts` is already called once by the sync mirror — the engine must **never** call it. Consider spreading ~100 redeems across ticks to avoid a tx burst.

## 9. Configuration (pydantic-settings; explicit `validation_alias` per field — no global prefix)

```python
liquidity_engine_enabled:      bool  = Field(False,          validation_alias="LIQUIDITY_ENGINE")           # prefix-less, like SYNC / SNAPSHOT_ENABLED
liquidity_interval_seconds:    float = Field(2.0,            validation_alias="AGENTPIT_LIQUIDITY_INTERVAL_SECONDS")
liquidity_house_account_count: int   = Field(100,            validation_alias="AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS")
liquidity_funding_drips:       int   = Field(1,              validation_alias="AGENTPIT_LIQUIDITY_FUNDING_DRIPS")          # 1 faucet drip = $1B
liquidity_split_per_market_usdc:int  = Field(10_000,         validation_alias="AGENTPIT_LIQUIDITY_SPLIT_PER_MARKET_USDC") # → 10K YES + 10K NO
liquidity_makers_per_market:   int   = Field(16,             validation_alias="AGENTPIT_LIQUIDITY_MAKERS_PER_MARKET")
liquidity_ladder_rungs_per_side:int  = Field(8,             validation_alias="AGENTPIT_LIQUIDITY_LADDER_RUNGS")
liquidity_wall_fraction:       float = Field(0.6,            validation_alias="AGENTPIT_LIQUIDITY_WALL_FRACTION")
liquidity_requote_threshold_micro:int= Field(2_000,         validation_alias="AGENTPIT_LIQUIDITY_REQUOTE_THRESHOLD")      # re-quote when mid moves ≥0.002
```

(1B apUSD/wallet × 100 = 1e17 micro total — fits BIGINT, ~9.2e18 max; this is exactly why the Phase-5a BIGINT audit mattered.) Defaults are conservative; everything tunable via env.

## 10. Testing

Real Postgres + forked Anvil (`scripts/run_node.sh` + `scripts/deploy_exchange.sh`), consistent with the existing suite. Layers:
- **Pure unit** (`ladder.py`): the U-shape sampler — distribution shape, non-crossing invariant, tick snapping — no DB/chain.
- **Provisioning** (real PG + Anvil): N accounts created, marked bot, funded, approved; **re-run is idempotent** (no dupes, count stable); re-onboard fires when `native_balance==0`.
- **Price oracle**: mid fetch + micro conversion; a fetch error on one market doesn't abort the tick (monkeypatch `get`).
- **Tick integration**: on an ACTIVE synced market, one tick yields a non-empty two-sided book, mid within tolerance of a stubbed Polymarket mid, and **zero trades** (assert no `trades` rows / all orders still `live`).

## 11. Open items (deferred, not blocking Stage 1)
- Stage 2 fill-rate target vs. the single-admin-lock ceiling (parallel admin signers only if truly needed).
- CLOB `/midpoint` rate limits at many-markets scale → batch `/midpoints` + cross-tick mid caching.
- NO-side mid: binary complement (`1 − YES`) vs. independent fetch.
- Capital recycling cadence (merge unsold sets vs. leave locked until redeem).
- Whether to also react to `ACTIVE→CANCELLED` (admin cancel) by clearing resting orders.
