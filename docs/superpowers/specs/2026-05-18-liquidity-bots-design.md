# Liquidity Bots — Design

**Date:** 2026-05-18
**Status:** Draft for implementation
**Scope:** v1 — deterministic Python bots that anchor AgentPit prices to Polymarket and keep order books alive. No LLM/OpenClaw integration.

---

## 1. Problem

AgentPit markets are dead. Two distinct symptoms:

1. **Empty order books.** Synced markets have no resting liquidity, so the UI shows nothing tradeable and any incoming order has nothing to match against.
2. **Stale prices.** Local mids don't track Polymarket — the same question can show $0.50 on AgentPit while Polymarket shows $0.78.

The term "arbitrage bot" doesn't quite fit: AgentPit uses simulated USDC, so there is no profit motive that would naturally pull prices toward Polymarket. We need a bot that **intentionally anchors** the local price and **provides depth**, plus a small amount of randomised trading so the book ticks and the last-traded price moves.

## 2. Goals & non-goals

**Goals (v1):**

- Local YES midpoint tracks Polymarket YES midpoint within ¢2 across all synced binary markets, within one tick interval of an upstream change.
- Every ACTIVE market with a `polymarket_condition_id` has resting bids and asks within ¢5 of the anchor on both YES and NO.
- Some markets see a few trades per minute (tunable platform-wide throughput) so charts and history tabs aren't flat.
- Bots run as an external service that uses the public REST API — no special server hooks.

**Non-goals (v1):**

- LLM-driven OpenClaw personality bots — separate effort.
- Historical trade/chart backfill — separate UI/data concern.
- Adversarial cross-market strategies (e.g. World Cup sub-markets summing >100%).
- Adaptive spreads, market impact modelling, inventory risk models.
- Bot monitoring UI — structured logs only.
- Promotion path to real Polymarket trading.

## 3. Architecture

External Python service (`agentpit_bots/`), launched as `python -m agentpit_bots.runner`. Authenticates against AgentPit as ordinary registered users via JWT, calls the public REST API for everything. Lives in the same repo; deployed as a separate process (systemd unit or docker-compose service alongside the API).

```
┌──────────────────────────────┐         ┌──────────────────────────┐
│  agentpit_bots.runner        │  HTTPS  │  AgentPit API            │
│  ─────────────────────       │ ──────► │  /register, /orders,     │
│   tick scheduler             │         │  /markets, /mint_usdc,   │
│   bot pool                   │         │  /split_position, ...    │
│   strategies                 │         └──────────────────────────┘
│   price oracle               │
└──────────────┬───────────────┘
               │ HTTPS (public CLOB)
               ▼
       ┌──────────────────┐
       │  Polymarket CLOB │  /midpoints, /prices (batched)
       └──────────────────┘
```

**Why external service, not in-process:**

- Same code path as real users — if bots can trade, real OpenClaw agents can too.
- Restart independence: server reboots don't kill bot state; bot crashes don't take down the API.
- Easy on/off (systemd disable).
- Doesn't compete with API request handlers for the DbSession rw_lock.

## 4. Components

```
agentpit_bots/                          (new package, run as module)
├── __init__.py
├── runner.py            # main loop: discover markets, schedule ticks per bot
├── price_oracle.py      # batched, cached Polymarket midpoint/price fetcher
├── strategies/
│   ├── __init__.py
│   ├── base.py          # Strategy ABC: compute_desired_orders(...)
│   ├── anchor_mm.py     # AnchorMarketMaker — one per market
│   └── noise_trader.py  # NoiseTrader — small pool, picks random market
├── bot_pool.py          # register, fund, split inventory, persist creds
├── client.py            # thin REST wrapper (auth, place, cancel, list orders)
├── reconcile.py         # diff (live orders, desired orders) → cancels + creates
├── config.py            # intervals, spreads, sizes, market enable/disable
└── creds.json           # gitignored — bot api keys + eth addresses

deployments/
└── (add systemd unit or docker-compose entry)
```

Each module is small and isolated. The interface boundary the runner sees is:

- `BotPool.bots() -> list[Bot]` — pre-registered, funded bots with strategy attached.
- `Strategy.compute_desired_orders(market, oracle_snapshot, bot_state) -> list[DesiredOrder]` — pure function.
- `reconcile(live, desired) -> (cancels, creates)` — pure function.
- `Client.cancel(order_id)`, `Client.place(DesiredOrder)` — IO.

## 5. Strategies

### 5.1 AnchorMarketMaker

One instance per ACTIVE market with a `polymarket_condition_id`. Per tick (default 30s):

1. `mid = oracle.midpoint(market.polymarket_yes_token_id)` — float in `[0, 1]`.
2. Target quotes for YES outcome:
   - `bid = clip(mid - half_spread, 0.01, 0.98)`
   - `ask = clip(mid + half_spread, 0.02, 0.99)`
3. Mirror onto NO outcome at `1 - mid ± half_spread`.
4. Reconcile against this bot's currently live orders for both outcomes: cancel orders outside the band, place any missing.

Defaults: `half_spread = $0.005` (so spread = ¢1), `size = 100 shares per quote`.

**Inventory rebalance.** Every Nth tick (default every 10th = every 5 min), check this bot's `(yes_balance, no_balance)`. If `min(yes, no) > rebalance_floor`, call `/markets/{id}/merge_positions` to recycle the matched pair into USDC. Keeps the bot from running out of either side asymmetrically.

**Graceful degradation.** If `oracle.midpoint(...)` returns a stale value (last refresh >5 min ago) or raises, skip new quote placement this tick but leave existing quotes in place. Logged as `oracle_stale`.

### 5.2 NoiseTrader

Small pool (default 3 bots), each ticks on a jittered interval (default 60s ± 20s). Per tick:

1. Pick a random ACTIVE market from the enabled set.
2. Pick a random size from `[5, 50]` shares.
3. With probability `p_aggressive` (default 0.3), post a marketable order that crosses the inside (lifts an ask or hits a bid) — generates a trade and ticks last-price.
4. Otherwise post a resting order just inside or outside the maker's band.

Pool size × per-bot interval determines platform throughput. Default of 3 bots × 60s = ~3 events/min platform-wide. Tunable in `config.py`.

## 6. Polymarket price oracle

Thin wrapper around the public Polymarket CLOB. `py_clob_client.ClobClient` already provides `get_midpoints(BookParams[])` and `get_prices(BookParams[])` — no auth needed for read endpoints.

- **Batched.** One HTTP call per tick fetches midpoints for every market the bots care about.
- **Cached.** In-memory `{token_id: (price, fetched_at)}`. Cache TTL = tick interval.
- **Graceful failure.** On HTTP error or timeout: keep stale values, log `oracle_fetch_failed`, return stale on next `midpoint(...)` call. Mark a token stale if `now - fetched_at > 5 min`.
- **Drift logging.** Once per minute, the runner logs `(market_id, local_mid, polymarket_mid, drift_cents)` for every enabled market. Makes "is it working?" observable.

## 7. Bot pool & wallets

Bots are ordinary users in the `users` table, distinguished by an `is_bot=1` flag.

Bootstrap (`BotPool.ensure_provisioned()` on runner startup):

1. For each bot in the config: if no row in `creds.json`, call `POST /register` and store the JWT + `eth_address`. Registration auto-funds the bot's `eth_address` with simulated USDC via `OnchainAdmin.faucet_drip` ([auth_service.py:83-91](../../../agentpit/services/auth_service.py#L83-L91)).
2. For each bot, mark it with the new admin endpoint `POST /admin/mark_bot`.
3. For each `AnchorMarketMaker` bot × each market it covers: call `POST /markets/{id}/split_position` once for `inventory_split_size` (default 500) so the bot has both YES and NO inventory and can post SELL orders immediately without waiting for a MINT match.

Top-up of bot USDC balance is **out of v1 scope**. The faucet drip should last for many days at the default order sizes; if a bot runs dry the operator registers a new bot. A dedicated admin top-up endpoint is a follow-up.

`creds.json` is gitignored. For production an env-var driven secret would be better; v1 keeps it local-file simple.

## 8. Schema changes

One migration in `agentpit/db/table_create.py`:

```sql
ALTER TABLE markets ADD COLUMN POLYMARKET_YES_TOKEN_ID TEXT;
ALTER TABLE markets ADD COLUMN POLYMARKET_NO_TOKEN_ID TEXT;
ALTER TABLE users   ADD COLUMN IS_BOT INTEGER NOT NULL DEFAULT 0;
```

The polymarket token IDs are currently discarded by `polymarket_sync.create_polygon_market_if_does_not_exist` ([polymarket_sync.py:529-531](../../../agentpit/polymarket/polymarket_sync.py#L529-L531)) when local CTF tokens overwrite them. Capture them from `pm_market["tokens"]` *before* the overwrite and persist on the `markets` row.

`IS_BOT` is set when `BotPool` registers a bot via a new admin-only endpoint `POST /admin/mark_bot` (body: `{eth_address}`), guarded by an `AGENTPIT_ADMIN_TOKEN` env var the runner also reads. Avoids leaking `is_bot` into the public `/register` surface. Future leaderboards/portfolio aggregations filter `IS_BOT = 0`.

## 9. Configuration

`agentpit_bots/config.py` exposes module-level constants:

```python
TICK_INTERVAL_SEC          = 30
NOISE_TICK_BASE_SEC        = 60
NOISE_TICK_JITTER_SEC      = 20
NOISE_POOL_SIZE            = 3
NOISE_AGGRESSIVE_PROB      = 0.3
NOISE_MIN_SIZE             = 5
NOISE_MAX_SIZE             = 50

MM_HALF_SPREAD_USD         = 0.005
MM_QUOTE_SIZE              = 100
MM_REBALANCE_EVERY_TICKS   = 10
MM_REBALANCE_FLOOR_SHARES  = 200

ORACLE_STALE_AFTER_SEC     = 300

DISABLED_MARKETS: set[int] = set()    # opt-out only; default = anchor every synced market
```

Per-market on/off is a config-file set (`DISABLED_MARKETS`). Default behaviour is "anchor every market with a `polymarket_condition_id`". Admin-endpoint-driven runtime toggling is out of scope for v1.

## 10. Data flow per anchor tick

```
runner.tick(market_id, bot):
   poly_yes_mid = oracle.midpoint(market.polymarket_yes_token_id)
   if oracle.is_stale(...):
       log("oracle_stale", market_id=market_id)
       return
   desired = strategy.compute_desired_orders(market, poly_yes_mid, bot.state)
   live    = client.list_live_orders(bot, market_id)
   cancels, creates = reconcile(live, desired)
   for c in cancels: client.cancel(bot, c.order_id)
   for n in creates: client.place(bot, n)
   if tick_index % MM_REBALANCE_EVERY_TICKS == 0:
       maybe_rebalance(client, bot, market_id)
```

`reconcile` is the only nontrivial pure-function piece: given live orders and desired (price, size, side, outcome) tuples, decide which live orders to cancel (off-band or wrong size) and which desired tuples need a new placement. Trivial to unit test.

## 11. Failure handling

- **Polymarket oracle down.** Anchor MM keeps existing quotes, posts none. Noise trader continues using stale prices (its randomness is the anchor MM's band, not Polymarket directly). Logged.
- **AgentPit `/orders` fails for one bot/market.** Log and continue — next tick retries. Single market failure must not abort the loop.
- **Bot runs out of USDC.** Log `bot_low_usdc bot=... balance=...` once per minute and skip placement that requires fresh collateral. Top-up itself is out of v1 scope — operator action.
- **Bot runs out of one outcome.** At tick start, if `min(yes_balance, no_balance) < quote_size`, call `/markets/{id}/split_position` to re-mint a complete set (subject to USDC available). Rebalance (§5.1) handles the opposite case (asymmetric *surplus*).
- **Runner crashes.** Restart from systemd. `creds.json` persists bot identities; `bot_state` (live orders) is reconstructed from `GET /orders` per bot on startup.

## 12. Observability

Structured logs only (v1):

- `tick_started market_id=... bot=... strategy=...`
- `oracle_snapshot fetched=12 stale=0 took_ms=...`
- `quotes_placed market_id=... bot=... yes_bid=... yes_ask=... no_bid=... no_ask=...`
- `quotes_cancelled market_id=... count=...`
- `noise_trade market_id=... bot=... side=... outcome=... price=... size=... filled=...`
- `drift market_id=... local_mid=... poly_mid=... drift_cents=...` (1×/min)
- `oracle_stale market_id=... token_id=... last_fetched=...`
- `topup_usdc bot=... old_balance=... minted=...`

Future: ship to Loki/CloudWatch and add a dashboard. Out of scope for v1.

## 13. Testing strategy

- **Unit:** `reconcile()`, `Strategy.compute_desired_orders()`, `PriceOracle` cache/stale logic — all pure functions, tested without HTTP.
- **Integration (mocked Polymarket):** runner against a `TestClient`-backed AgentPit + a fake oracle that returns scripted prices; assert that after N ticks the local mid is within tolerance of the scripted price.
- **Integration (live, opt-in):** `@integration` test that points at the live Polymarket CLOB + a local AgentPit, runs for 5 ticks, asserts drift < ¢5 on at least one synced market.

## 14. Out-of-scope items (deferred, listed for future reference)

- LLM-driven OpenClaw personality bots that reason about beliefs/methods/needs.
- Historical chart backfill (synthetic trades to fill empty charts).
- Adaptive spreads based on upstream book depth.
- Cross-market sanity (e.g. World Cup sub-markets normalised to 100%).
- Admin REST endpoints for runtime bot toggling.
- Bot monitoring UI / dashboards.
- Production secret management for `creds.json`.

## 15. Open questions / risks

- **On-chain settlement load.** Every cross-match becomes a real `CTFExchange.matchOrders` tx on the local Anvil. 3 noise trades/min × multiple match events each = a few txs/min. Should be fine on Anvil but worth watching.
- **Polymarket rate limits.** Public CLOB endpoints have unstated limits. 30s polling × batched midpoints should stay well under, but if we ever scale to hundreds of markets, may need WebSocket subscription instead.
- **The local token ID is *not* the Polymarket token ID** ([polymarket_sync.py:529-531](../../../agentpit/polymarket/polymarket_sync.py#L529-L531)). The new `POLYMARKET_YES_TOKEN_ID` / `POLYMARKET_NO_TOKEN_ID` columns are the only link back. If the sync ever re-runs and the upstream tokens change (unlikely, but possible if Polymarket re-issues a market), the bot would silently anchor to the wrong upstream — sync should be idempotent on this.
