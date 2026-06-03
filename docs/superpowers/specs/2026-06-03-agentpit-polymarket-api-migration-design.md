# agentpit → Polymarket API migration — design spec

**Status**: design, pending implementation plan
**Date**: 2026-06-03
**Driver**: `docs/missing-features/` (features 01–04) + the `agentpit-trader` design spec. Supersedes the four missing-features docs by absorbing them into a single coherent migration.

---

## 1. Context & goal

`agentpit` is a **paper-trading test platform** for the `agentpit-trader` LLM bot. The workflow is: the bot discovers a working trading strategy on agentpit (using fake, freely-mintable tokens with no real risk), then runs that *same strategy* against **real Polymarket** for real money.

For that swap to be safe, the bot must be able to point at either backend and have its **request-building and response-parsing code be identical**. Any shape discrepancy between agentpit and Polymarket risks runtime errors precisely when the bot moves to real money.

Therefore: **agentpit's HTTP API becomes an exact copy of Polymarket's API at the *interface* level** — same routes, same request/response JSON shapes, same field names, same value representations. This is a **full switch**: the existing agentpit-flavored trading endpoints are migrated in place to Polymarket's paths/shapes and the old ones deleted; the agentpit UI is reworked in lockstep to consume the new shapes. One surface, no "is this the agentpit way or the Polymarket way?" ambiguity.

### What "interface parity" does and does not mean

- **Does mean**: identical routes, identical request bodies (at the logical level), identical response JSON (field names, types, decimal-string vs float conventions, ordering).
- **Does NOT mean**: replicating Polymarket's *internal* protocol. agentpit keeps its simple internals — server-side order signing, its existing bearer/api-key auth, off-chain matching + admin on-chain settlement. The bot never sees these, and Polymarket's backend is closed-source, so there is nothing to match.

### The one irreducible difference: identifier *values*

agentpit is its own chain/deployment, so its `condition_id` and `token_id` **values** differ from Polymarket's. The *shapes* match, but the *values* are backend-specific. The bot translates Polymarket identifiers → agentpit identifiers via the **bridge** (§6). This is inherent and harmless — it lives entirely in the bot's thin per-venue adapter.

---

## 2. Non-goals / explicitly deferred

These are deliberately **out of scope** — they are the "multi-week" items the trader README flagged, and a paper test rig does not need them:

1. **L2 HMAC auth parity** (the five `POLY_*` headers + `createOrDeriveApiKey` key derivation). agentpit keeps its current bearer/api-key auth. The bot's adapter sets the right auth per venue.
2. **Client-signed EIP-712 order intake.** `POST /order` accepts Polymarket's *logical order args* (`token_id, price, size, side, order_type, expiration`), not a signed order struct. agentpit signs server-side undercover, as it does today.
3. **Full Gamma `Market` fidelity** (all ~60 fields). We match the ~20-field practical subset the bot + UI use (§8.11), with Gamma's exact names/encoding.
4. **`split` / `merge` / `redeem` as Polymarket REST endpoints.** Polymarket has no CLOB REST equivalent (they are on-chain CTF ops); their *effects* surface in `/activity`. agentpit keeps them as native endpoints.
5. **WebSocket parity** (market/user channels). 30-minute trader cadence doesn't need streams.
6. **Bulk `POST /orders` (batch place).** Trader places one order at a time in v1.

If/when the bot must drive the *official* `@polymarket/clob-client` against agentpit unmodified, items 1–2 become a follow-up project.

---

## 3. Architecture

The migration happens **in place** in the existing `agentpit/api/` package — there is no separate "polymarket" API package (that would recreate the two-surface confusion the full switch removes).

| Concern | Location |
|---|---|
| Routes (now Polymarket-shaped) | `agentpit/api/routes/*.py` (rewrite handlers; delete obsolete routes as replaced) |
| Response/request models | `agentpit/datastructures/*.py` (flat, per codebase convention; replace obsolete models) |
| Value converters + identifier resolver | `agentpit/polymarket/format.py` + `agentpit/polymarket/resolve.py` (the existing `agentpit/polymarket/` domain package) |
| Services (matching/settlement) | `agentpit/services/*.py` (largely unchanged; data source for serialization) |

**Converters** (`agentpit/polymarket/format.py`) — the single home for representation logic so every endpoint is consistent:
- `price_to_decimal_str(price_int) -> str` — `360000 → "0.36"` (÷ `_PRICE_ONE` = 10⁶).
- `price_to_float(price_int) -> float` — `360000 → 0.36` (for Data-API / prices-history families).
- `size_to_decimal_str(micro_units) -> str` — `30_000_000 → "30"` (÷ 10⁶).
- `size_to_float(micro_units) -> float` — for the Data-API family.
- Inverses: `decimal_str_to_price_int`, `decimal_str_to_size_micro` for request parsing.

**Resolver** (`agentpit/polymarket/resolve.py`) — bidirectional identity:
- `resolve_by_market_outcome(market_id, outcome) -> (market, token_id, condition_id, outcome_index)` (today's `_resolve_market_lookup`, lifted out of `OrderService`).
- `resolve_by_token_id(token_id) -> (market, condition_id, outcome_label, outcome_index)` — new reverse lookup (the `markets` table is queried by `ERC1155_TOKENS LIKE` today in `_complement_token_id`; generalize it).

**Models** match Polymarket's **exact field names and casing per endpoint** — mostly snake_case, except the `POST /order` response which is camelCase (`orderID`, `errorMsg`, `transactionsHashes`), which agentpit's existing `OrderResponse` already does. This supersedes the earlier blanket "snake_case" decision: the rule is *match Polymarket exactly*, endpoint by endpoint.

---

## 4. Representation conventions (critical reference)

There is **no single convention** — each Polymarket API family encodes values differently. We must replicate each one exactly.

| Family | Endpoints | Price/size | Timestamps |
|---|---|---|---|
| **CLOB** | `/book`, `/data/orders`, `/data/trades`, `/order`, `/midpoint`, `/price`, `/balance-allowance` | **decimal strings** (`"0.36"`, `"100"`) | `/book` `timestamp` = **ms string**; orders/trades = **unix seconds string** (`created_at` may be num); `prices-history` `t` = **int seconds**, `p` = **float** |
| **Data API** | `/positions`, `/value`, `/activity` | **plain JSON floats** (`0.36`, `100`) | **int seconds** |
| **Gamma** | `/markets`, `/events` | `volume/liquidity/outcomePrices` = **strings**; `bestBid/bestAsk/lastTradePrice/volumeNum` = **numbers**; `outcomes/clobTokenIds/outcomePrices` = **JSON arrays encoded as strings** (`"[\"Yes\",\"No\"]"`) | ISO strings (`endDateIso`) |

agentpit stores everything as scaled ints internally (`_PRICE_ONE = 10**6` = $1.00; 1 token = 10⁶ units, `_USDC_DECIMALS = 6`). All conversion happens at the serialization boundary via §3 converters — internal storage is untouched.

**OpenAPI-vs-live divergences** (Polymarket's own surfaces disagree; verify per-endpoint at implementation). Where they differ, agentpit follows the **live API / SDK** form, because that is what a real bot parses:
- **Status enums are unprefixed** (`LIVE`, `MATCHED`) — not the OpenAPI's `ORDER_STATUS_*` / `TRADE_STATUS_*` prefixes.
- **CLOB share sizes are human decimals** (`"100"`) — `OpenOrder.original_size`/`size_matched` and `Trade.size`/`matched_amount` — not the OpenAPI's 6-decimal fixed-math integer strings. **Exception:** `/balance-allowance.balance`, which *does* use the base-unit integer-string form (§8.12).
- **Prices remain plain decimal strings** (`"0.36"`) everywhere in the CLOB family.

---

## 5. The migration map (also the "done / missing" tracker)

| agentpit today | → Polymarket target | Status | Phase |
|---|---|---|---|
| `POST /orders` | `POST /order` | Partial — add `token_id`, `transactionsHashes`, exact `postOrder` response | 2 |
| `DELETE /orders/{id}` | `DELETE /order` `{orderID}` → `{canceled,not_canceled}` | Partial — reshape; 200 on not-found | 2 |
| — | `DELETE /orders`, `/cancel-all`, `/cancel-market-orders` | Missing (siblings) | 2 |
| `GET /orders/mine` | `GET /data/orders` → `OpenOrder[]` | Partial | 2 |
| `GET /orderbook/{id}/{outcome}` | `GET /book?token_id=` → `OrderBookSummary` | Partial — aggregate + decimal strings | 3 |
| — | `POST /books` (batch book) | Missing (sibling of `/book`) | 3 |
| `GET /sparkline/{id}/{outcome}` | `GET /prices-history?market=token_id` → `{history:[{t,p}]}` | Partial — `p`→float, drop volume | 3 |
| — | `GET /midpoint`, `/price`, `/last-trade-price` | Missing (derive from book/trades) | 3 |
| *(trades table, unexposed)* | `GET /data/trades` → CLOB `Trade[]` | Missing — needs ledger owner-attribution | 4 |
| `GET /portfolio` | Data-API `GET /positions` (+ `/value`) | Partial — float repr, add pricing/PnL | 4 |
| `GET /transactions` | Data-API `GET /activity` | Partial — reshape + wire SPLIT/MERGE/REDEEM + fills | 4 |
| `GET /usdc_balance` | CLOB `GET /balance-allowance` | Partial — int → `{balance, allowances}` (§8.12) | 4 |
| `GET /markets` (+filters), `/markets/{id}` | Gamma `GET /markets` (+ `/{id}`) | Partial — Gamma subset + bridge filter | 1 |
| `GET /events`, `/events/{slug}` | Gamma `GET /events` | Partial | 1 |

**Stay agentpit-native** (no Polymarket equivalent — unchanged): `register`/`login`, `GET/PATCH /me`, `admin/mark_bot`, `POST /markets` + lifecycle (`activate`/`close`/`cancel`/`resolve`), `split`/`merge`/`redeem` position ops, `create_personality`, `create_agent`, `GET /` health.

---

## 6. The identifier bridge (feature 02)

The bot holds Polymarket `conditionId`s. To act on agentpit it needs agentpit's `token_id`s. The bridge is a filter on the (now Gamma-shaped) markets endpoint:

```
GET /markets?clob_token_ids=…           # by agentpit token id
GET /markets?condition_ids=…            # by agentpit native condition_id
GET /markets?polymarket_condition_id=…  # BRIDGE: by upstream Polymarket conditionId
```

- agentpit markets carry a native `CONDITION_ID` (NOT NULL, UNIQUE, u256 hex) → exposed as Gamma `conditionId` / the `market` field everywhere.
- The nullable `POLYMARKET_CONDITION_ID` is the **bridge key** for markets mirrored from Polymarket.
- The returned market carries `clobTokenIds` (= agentpit's `erc1155_tokens` token_ids), which the bot then uses against `/book`, `/data/orders`, `/data/trades`, `/order`, etc.

Implementation: dynamic `WHERE` in raw SQL inside `TableRead.list_markets` (the codebase uses raw `sqlite3`, **not** SQLAlchemy — the missing-features doc's ORM snippet does not apply). Indexes already exist on `CONDITION_ID` and `POLYMARKET_CONDITION_ID`.

---

## 7. Data-model changes

Only the **`trades` table** needs structural change; markets/orders already carry what's needed.

Current `trades` columns: `TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID, PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS, MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS`. Two problems:

1. **No owner attribution** → fills cannot be queried per user. **Add** `TAKER_API_KEY` and `MAKER_API_KEY` columns, populated in `OrderService._insert_trade`. The taker key is the placing order's `API_KEY`; the maker key is `maker_row["API_KEY"]` — `maker_row` is a full `orders` row, so both `API_KEY` and `MAKER` (the eth address) are available. **These columns are internal filter keys only; they are never serialized.** The wire `owner` field is the non-secret `USER_ID` (§8.3/§13), resolved from the api_key via the `users` table — agentpit's api_key is the bearer credential and must never appear in a response body.
2. **`MARKET` currently stores the token_id**, not the condition_id (in `_insert_trade`, both `MARKET` and `ASSET_ID` are set to `taker_row["TOKEN_ID"]`). Polymarket semantics require `market` = condition_id, `asset_id` = token_id. **Fix**: resolve condition_id from token_id at insert time (via §3 resolver) and store it in `MARKET`; keep `ASSET_ID` = token_id.

Migration is additive (new nullable columns + a backfill that recomputes `MARKET`), consistent with the existing `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` idempotent-migration pattern in `table_create.py`.

`OrderService._insert_trade` also currently writes **one row per match** and stores a minimal `MAKER_ORDERS` payload whose `owner` is today the maker's `MAKER` eth address ([order_service.py:509](../../../agentpit/services/order_service.py#L509)). For `/data/trades` parity (§8.4) the `MAKER_ORDERS` JSON must be enriched to the full `MakerOrder` shape — `owner` **flips** from `MAKER` to the maker's non-secret `USER_ID`, and a separate `maker_address` = `MAKER` is added — and a single match must be serializable from **both** the taker's and a maker's perspective (`trader_side` toggles) at read time.

---

## 8. Endpoint contracts

For each, the exact Polymarket shape is the contract; the agentpit source + conversions are notes for implementation. All prices/sizes go through §3 converters.

### 8.1 `POST /order` — place order (CLOB)

**Request** (logical order args; **not** a signed struct):
```json
{ "token_id": "<agentpit token id>", "price": 0.36, "size": 100,
  "side": "BUY", "order_type": "GTC", "expiration": 0 }
```
- `token_id` is **required and canonical**; it resolves to `(market_id, outcome)` via the §3 resolver. A transitional `market_id`+`outcome` fallback is accepted **only when `token_id` is absent**; if both are present, `token_id` wins and a conflicting pair is a `4xx`. The fallback is **removed at the end of Phase 2** (once the UI sends `token_id`).
- `price` is a 0–1 number (snapped to the 0.1¢ tick, as today); `size` is whole shares (× 10⁶ internally).

**Response** (exact `postOrder` shape):
```json
{ "success": true, "errorMsg": "", "orderID": "0x…",
  "status": "live", "transactionsHashes": ["0x…"],
  "takingAmount": "", "makingAmount": "", "tradeIDs": [] }
```
- `status` ∈ `live | matched | delayed` (lowercase; the documented HTTP enum — `unmatched` is SDK-only and agentpit never emits it). agentpit produces only `live` and `matched`; `delayed` is unreachable. Settlement failure → `success:false` + `errorMsg`, not a status.
- `transactionsHashes` (note: *transactions* + *Hashes*) = agentpit's settlement tx hashes as an array (today `OrderResponse.txHash` is a comma-joined string → split to array).
- **Update `OrderResponse` in place** (no parallel model): it already matches `success`/`errorMsg`/`orderID`/`status`. **Remove** `filledSize`/`remainingSize`/`avgPrice` (Polymarket has no such fields); **add** `transactionsHashes: list[str]`, `takingAmount`/`makingAmount` (from the immediate match if present, else `""`), and `tradeIDs: list[str]`.

### 8.2 `DELETE /order` + siblings — cancel (CLOB)

| Route | Body | 
|---|---|
| `DELETE /order` | `{ "orderID": "<id>" }` |
| `DELETE /orders` | `["<id>", …]` (bare array, max 3000) |
| `DELETE /cancel-all` | *(none)* |
| `DELETE /cancel-market-orders` | `{ "market": "<condition_id>", "asset_id": "<token_id>" }` (both optional) |

**Response** (uniform `CancelOrdersResponse`, **HTTP 200 always** for valid auth):
```json
{ "canceled": ["<id>"], "not_canceled": { "<id>": "<reason>" } }
```
- `canceled` (American spelling, single 'l'), `not_canceled` (snake_case). Empty `{}` on full success.
- **Stop raising 404** for not-found/already-cancelled — record it in `not_canceled` with a reason string. Reserve non-200 for request-level errors (bad payload, auth). Reason strings are not a stable Polymarket enum; a robust bot checks presence-in-`not_canceled`, not the text.

### 8.3 `GET /data/orders` — open orders (CLOB)

**Query**: `market` (condition_id), `asset_id` (token_id), `id` — all optional, AND-combined. Filtered to the authenticated user.

**Response**: bare array of `OpenOrder`:
```json
{ "id": "0x…", "status": "LIVE", "owner": "<api-key>", "maker_address": "0x…",
  "market": "<condition_id>", "asset_id": "<token_id>", "side": "BUY",
  "original_size": "100", "size_matched": "15", "price": "0.36",
  "associate_trades": ["<tradeId>"], "outcome": "Yes",
  "created_at": 1709234567, "expiration": "0", "order_type": "GTC" }
```
- No `remaining` field (bot computes `original_size - size_matched`). agentpit stores `REMAINING_AMOUNT` only → also need the order's **original** size: derive `size_matched = original - remaining` (original = `MAKER_AMOUNT`/`TAKER_AMOUNT` by side, already on the row). `original_size`/`size_matched` are emitted as **human-decimal share strings** (`"100"`), per the live-API form (§4).
- `owner` = the order's **`USER_ID`** (non-secret), **never** the api_key (§13); `maker_address` = `MAKER`. `market` requires token_id→condition_id resolution. `outcome`/`status` use the **unprefixed** live-API form (`LIVE`, not `ORDER_STATUS_LIVE`; §4). `associate_trades` = trade ids joined from the trades ledger (ship `[]` initially if join is deferred).
- **v1 wire shape: a bare `OpenOrder[]` array** (what the SDK returns after flattening). Cursor pagination is deferred — paper-rig order counts are small.

### 8.4 `GET /data/trades` — fills (CLOB)

**Query**: `market`, `asset_id`, `id`, `maker_address`, `before`, `after` (unix sec), `next_cursor`. Filtered to the authenticated user as taker **or** maker.

**Response**: array of `Trade` (raw HTTP wraps in `{limit,count,next_cursor,data}`):
```json
{ "id": "<tradeId>", "taker_order_id": "0x…", "market": "<condition_id>",
  "asset_id": "<token_id>", "side": "BUY", "size": "30", "fee_rate_bps": "0",
  "price": "0.36", "status": "MATCHED", "match_time": "1700000000",
  "last_update": "1700000000", "outcome": "Yes", "bucket_index": 0,
  "owner": "<api-key>", "maker_address": "0x…",
  "maker_orders": [ { "order_id": "0x…", "owner": "<api-key>", "maker_address": "0x…",
      "matched_amount": "30", "price": "0.36", "fee_rate_bps": "0",
      "asset_id": "<token_id>", "outcome": "Yes", "side": "SELL" } ],
  "transaction_hash": "0x…", "trader_side": "TAKER" }
```
- `bucket_index` is the only int; everything else string. `match_time` is a **string** of unix seconds (agentpit stores int → stringify). `size`/`matched_amount` are human-decimal share strings (§4).
- `trader_side` = `TAKER` when the querying user owns the taker order, `MAKER` when they own a maker order. The same match serializes from either perspective at read time (per §7 enrichment).
- `owner` (top-level **and** inside each `maker_orders[]`) is the party's **`USER_ID`** (non-secret), never the api_key — this matters most for the *counterparty's* `owner` surfaced in another user's feed (§13).
- **v1 wire shape: the `{limit, count, next_cursor, data: Trade[]}` envelope** (the raw HTTP shape the bot's adapter parses); `next_cursor` = the end sentinel `LTE=` when unpaged.
- Source: the enriched `trades` table. `status` maps agentpit trade status (`PENDING`/settled/`FAILED`) → unprefixed `MATCHED`/`CONFIRMED`/`FAILED` (not the OpenAPI `TRADE_STATUS_*` prefix; §4).

### 8.5 `GET /book` — order book (CLOB)

**Query**: `token_id` (single outcome). Also `POST /books` with `[{token_id, side}]` → `OrderBookSummary[]`.

**Response** (`OrderBookSummary`):
```json
{ "market": "<condition_id>", "asset_id": "<token_id>",
  "timestamp": "1740000000000", "hash": "…",
  "bids": [ {"price":"0.45","size":"120"} ], "asks": [ {"price":"0.55","size":"90"} ],
  "min_order_size": "5", "tick_size": "0.001", "neg_risk": false,
  "last_trade_price": "0.46" }
```
- **Aggregate per price level** (today agentpit returns one row per resting order): `GROUP BY PRICE`, sum `REMAINING_AMOUNT`. Drop `ORDER_ID`/`MAKER`/`CREATED_AT`/`SIDE`.
- `bids` price-descending, `asks` price-ascending (already the sort order). Prices/sizes → decimal strings.
- `timestamp` = ms epoch string. `tick_size` = `"0.001"` (agentpit's `_PRICE_TICK`). `neg_risk`/`min_order_size` derived from market config (default `false`/a constant).
- `last_trade_price` (decimal string) from the trades ledger (§8.4) — the CLOB OpenAPI marks it required on `OrderBookSummary`.

### 8.6 `GET /prices-history` — price history (CLOB)

**Query**: `market` (= token_id), `startTs`, `endTs` (unix sec), `interval` (`max|1m|1w|1d|6h|1h`), `fidelity` (minutes).

**Response**:
```json
{ "history": [ {"t": 1678886400, "p": 0.505} ] }
```
- agentpit's `/sparkline` already emits `{t,p}` with `t` = int seconds — keep. Changes: rename `points`→`history`, `p` int → **float 0–1**, **drop** `volume_micro_usd`/`volume_total_micro_usd` (Polymarket has none), ascending by `t`.
- Map `interval`/`fidelity` onto the existing windowing (`window_hours`) + downsample; `1m` = one *month*.

### 8.7 `GET /midpoint`, `GET /price`, `GET /last-trade-price` (CLOB)

- `GET /midpoint?token_id=` → `{ "mid": "0.50" }` (avg best bid/ask from the book; 404 if no book).
- `GET /price?token_id=&side=BUY|SELL` → `{ "price": "0.55" }` (`BUY`→best ask, `SELL`→best bid). `side` is a required **request** param.
- `GET /last-trade-price?token_id=` → `{ "price": "0.52", "side": "BUY" }` (from the trades ledger). All decimal strings. Cheap derivations from §8.5/§8.4. It reads only the trades table's `PRICE`/`SIDE`/`MATCH_TIME` by `ASSET_ID` — columns that exist **before** the Phase-4 owner-attribution enrichment — so it ships cleanly in Phase 3 against the raw table.

### 8.8 `GET /positions` — Data API

**Query**: `user` (eth_address), optional `market` (condition_ids), `limit`/`offset`/`sortBy`/`sortDirection`, etc.

**Identity model** (applies to `/positions`, `/value`, `/activity`): like Polymarket, these Data-API endpoints are **public-by-address** — `user` is an agentpit user's eth address (resolved against the `users` table), **no auth required**. (The CLOB reads `/data/orders` and `/data/trades` stay auth-filtered to the calling api_key.) The bot passes its agentpit eth address as `user`.

**Response**: array of position objects (**floats**):
```json
{ "proxyWallet": "0x…", "asset": "<token_id>", "conditionId": "<condition_id>",
  "size": 100.0, "avgPrice": 0.36, "initialValue": 36.0, "currentValue": 40.0,
  "cashPnl": 4.0, "percentPnl": 11.1, "totalBought": 36.0, "realizedPnl": 0.0,
  "percentRealizedPnl": 0.0, "curPrice": 0.40, "redeemable": false,
  "title": "…", "slug": "…", "icon": "…", "eventSlug": "…",
  "outcome": "Yes", "outcomeIndex": 0, "oppositeOutcome": "No",
  "oppositeAsset": "<token_id>", "endDate": "…", "negativeRisk": false }
```
- agentpit `PortfolioResponse.positions` has `market_id, question, token_id, outcome_label, outcome_index, balance(int)`. Map: `asset`=token_id, `conditionId`=resolved, `size`=balance/10⁶ (float), `outcome`/`outcomeIndex` direct, `title`=question, `oppositeAsset`=complement token.
- **Pricing/PnL** (`avgPrice`, `curPrice`, `cashPnl`, …) are new: `avgPrice` from the user's fills (trades ledger), `curPrice` from the book midpoint. Where a value is unavailable, emit a defensible default (e.g. `0.0`) rather than omitting the field — shape stays exact.

### 8.9 `GET /value` — Data API

`GET /value?user=` → array of one object: `[ { "user": "0x…", "value": 40.0 } ]` — total **float** USD mark-to-market of the user's positions (distinct from cash USDC). Derived from §8.8.

### 8.10 `GET /activity` — Data API (replaces `/transactions`)

**Query**: `user`, `limit`/`offset`, `market`, `type` (`TRADE,SPLIT,MERGE,REDEEM,REWARD,CONVERSION`), `start`/`end` (unix sec), `side`, `sortBy`/`sortDirection`.

**Response**: array of activity objects (**floats, int-seconds**):
```json
{ "proxyWallet": "0x…", "timestamp": 1700000000, "conditionId": "<condition_id>",
  "type": "TRADE", "size": 30.0, "usdcSize": 10.8, "transactionHash": "0x…",
  "price": 0.36, "asset": "<token_id>", "side": "BUY", "outcomeIndex": 0,
  "title": "…", "slug": "…", "icon": "…", "eventSlug": "…", "outcome": "Yes",
  "name": "…", "pseudonym": "…", "bio": "…", "profileImage": "…", "profileImageOptimized": "…" }
```
- `TRADE` rows derive from the trades ledger (per user). `SPLIT`/`MERGE`/`REDEEM` rows come from the position-primitive flows — **wire up `TableWrite.log_transaction` in `split`/`merge`/`redeem`**, which today is never called (the transactions table is effectively empty). This satisfies missing-features doc 01's "fix SPLIT/MERGE/REDEEM logging" and emits fills for **all** match kinds (NORMAL + MINT/MERGE; both already flow through `_match`→`_insert_trade`).
- Profile fields (`name`/`pseudonym`/…) populate from the agentpit user where available, else `""`/`null`.

### 8.11 Gamma `GET /markets` + `/events`

**Response** — Gamma `Market` **practical subset** (exact names + encoding):
```json
{ "id": "<market_id>", "conditionId": "<condition_id>", "question": "…", "slug": "…",
  "description": "…", "outcomes": "[\"Yes\",\"No\"]", "outcomePrices": "[\"0.5\",\"0.5\"]",
  "clobTokenIds": "[\"<tok0>\",\"<tok1>\"]", "active": true, "closed": false,
  "acceptingOrders": true, "startDate": "…", "endDate": "…", "endDateIso": "…",
  "icon": "…", "image": "…", "volume": "0", "liquidity": "0",
  "bestBid": 0.45, "bestAsk": 0.55, "lastTradePrice": 0.46, "spread": 0.10 }
```
- `outcomes`/`outcomePrices`/`clobTokenIds` are **JSON arrays encoded as strings** (Gamma's quirk — replicate exactly). `clobTokenIds` = agentpit's `erc1155_tokens` token_ids in `[yes, no]` order; `outcomes` = the labels.
- `volume`/`liquidity`/`outcomePrices` are **strings**; `bestBid`/`bestAsk`/`lastTradePrice`/`spread` are **numbers** (from the book/trades).
- `market_state` maps to `active`/`closed`/`acceptingOrders` booleans. The **bridge filters** (§6) attach here.
- `/events` mirrors Gamma's event object (`id, slug, title, description, markets[], …`) over agentpit's `EventWithMarkets`.
- Omitted (deferred): the ~40 unused Gamma fields (`umaBond`, `gameId`, `makerBaseFee`, rewards, tags internals, …).

### 8.12 `GET /balance-allowance` — CLOB (replaces `/usdc_balance`)

**Query**: `asset_type` (`COLLATERAL` for USDC | `CONDITIONAL` for an outcome token), `token_id` (required when `CONDITIONAL`), `signature_type`.

**Response** (raw CLOB `BalanceAllowanceResponse`): `{ "balance": "1000000000", "allowances": {} }` — `balance` is a **base-unit integer string** (6-decimal fixed-math; `1000000000` = 1000 USDC), `allowances` is a **`{spender: amount}` map** (plural). agentpit has no allowance tracking → emit `allowances: {}`. For `COLLATERAL`, the USDC balance; for `CONDITIONAL` (requires `token_id`), the outcome-token (CTF) balance. `signature_type` is **accepted and ignored** (agentpit has no signature-type concept; §2). *(The py-clob-client SDK flattens this to a singular `{balance, allowance}` of human decimals; we match the **raw HTTP** shape since the bot parses HTTP directly.)*

### 8.13 Outcome contract (feature 04)

`token_id` becomes the canonical order identifier (§8.1), so the `outcome` label contract matters only for the native UI path and `outcome` fields in responses. Decision: keep matching **case-insensitive** (current behavior, non-breaking), add a `Field` description documenting it's a label matched against `erc1155_tokens[i][1]`, and on no-match raise a clear error listing valid labels.

---

## 9. UI migration

The UI is **centralized**: all HTTP goes through `ui/src/api/client.ts` (`apiFetch`), per-resource modules (`ui/src/api/{orders,markets,events,portfolio,auth}.ts`), shapes typed in `ui/src/types/{order,market,event}.ts`, consumed by ~15 components via React Query hooks. Migration is per-resource: rewrite the `api/*.ts` parser + `types/*.ts`, then fix the components that read raw fields.

Endpoints the UI actually consumes (others — `/data/orders`, `/data/trades`, `/activity`, `/balance-allowance` — are bot-only and need no UI work now):

| UI module | calls | components to update |
|---|---|---|
| `api/events.ts` | `/markets` (Gamma), `/events` | `MarketsPage`, `EventDetailPage`, `MarketCard`, `MultiMarketEventCard` |
| `api/markets.ts` | `/markets/{id}`, `/prices-history` (was `/sparkline`) | `MarketDetailPage`, `MarketCard`, `EventChart`, `Sparkline` |
| `api/orders.ts` | `POST /order`, `DELETE /order`, `/book` (was `/orderbook`) | `OrderTicket`, `Orderbook`, `EventLeaderboardRow`, `lib/useYesMid.ts`, `orderMath.ts` |
| `api/portfolio.ts` | `/positions` (was `/portfolio`) | `OrderTicket`, `ProfilePage` |

The typed shapes in `ui/src/types/{order,market,event}.ts` are the **ground truth** — changing a type cascades compile errors at every stale consumer (good coverage). The concrete shape changes:
- **`OrderbookEntry` → `{price: string, size: string}`** (drop `ORDER_ID`/`SIDE`/`MAKER`/`CREATED_AT`; prices/sizes become 0–1 decimal strings). This removes **all** micro-int math — `Math.max(...bids.map(b => b.PRICE)) / 1_000_000` in [useYesMid.ts](ui/src/lib/useYesMid.ts) and [orderMath.ts](ui/src/components/orders/orderMath.ts) becomes `parseFloat(price)` — not re-scaled. (The mid is still computed client-side from `/book`; `/midpoint` is available but the UI need not switch to it.)
- **`OrderResponse`** loses `filledSize`/`remainingSize`/`avgPrice`; `OrderTicket` must derive filled/remaining from order state + `/data/trades` instead of the place response.
- **`PlaceOrderRequest` → `{token_id, price, size, side, order_type, expiration}`**; `OrderTicket` resolves `token_id` from the loaded market's `clobTokenIds`/`erc1155_tokens` by the selected outcome label.
- **`Market`** → Gamma subset (`id`, `conditionId`, `outcomes`/`clobTokenIds`/`outcomePrices` as JSON-string arrays, `active`/`closed`/`acceptingOrders`); **`SparklinePoint.p`** → float 0–1 and the array key `points` → `history`.

Highest-touch is the order-book mid fan-out ([useYesMid.ts](ui/src/lib/useYesMid.ts) → `MarketCard`, `MultiMarketEventCard`, `EventLeaderboardRow`, `OrderTicket`). Per the §8.1 transition, the UI **leads** by sending `token_id`; the `POST /order` `market_id`+`outcome` fallback is removed at the end of Phase 2.

---

## 10. Phasing (one spec, five reviewable phases)

Each phase is independently shippable, fully tested, and migrates backend + UI together so the app never breaks.

- **Phase 1 — Foundation + markets/events.** Converters (`format.py`), resolver (`resolve.py`), Gamma-subset `/markets` (+`/markets/{id}`) with the §6 bridge filters, Gamma `/events`. UI: `api/events.ts`, `api/markets.ts` (markets only), types, card/detail components.
- **Phase 2 — Trading core.** `POST /order` (logical args + exact response, `token_id` canonical), `DELETE /order` + siblings, `GET /data/orders`. UI: `api/orders.ts` place/cancel, `OrderTicket`.
- **Phase 3 — Market data.** `GET /book` (+`/books`), `/prices-history`, `/midpoint`, `/price`, `/last-trade-price`. UI: `api/orders.ts` book + `useYesMid`, `api/markets.ts` sparkline→prices-history, `Orderbook`/`MarketCard`/`EventChart`.
- **Phase 4 — Fills, positions, balance, activity.** `trades` table enrichment + `/data/trades`; `/positions` (+`/value`); `/balance-allowance`; `/activity` + SPLIT/MERGE/REDEEM logging. UI: `api/portfolio.ts`→positions, `ProfilePage`/`OrderTicket`.
- **Phase 5 (final) — internal API consumers (`agentpit_bots` + dev scripts).** The in-repo simulation bot pool (`agentpit_bots/`) and the standalone dev seed script (`scripts/seed_market_orders.py`) are API consumers the §9 UI migration does not cover. They call the pre-migration paths/shapes (`/markets`→`["markets"]`, `POST /orders` with raw-micro `size`, `/orders/mine`, `DELETE /orders/{id}`, `res["filledSize"]`, `/orderbook/{id}/{outcome}`, `/portfolio`); `agentpit_bots`' unit tests mock the server, and the seed script is standalone (never imported by tests), so the suite stays green while both drift out of sync with the live API. **Decision (2026-06-03 checkpoint): defer the whole consumer migration to this single final pass** rather than migrating per-phase. This phase rewrites `agentpit_bots/client.py` (+ `runner`/`strategies`/`reconcile` call sites and `tests/bots/`) and `scripts/seed_market_orders.py` onto the migrated endpoints (`/markets` bare Gamma array, `POST /order` with `token_id` + share-denominated `size`, `GET /data/orders`, `DELETE /order`, `/book`, `/prices-history`, `/positions`, `/balance-allowance`).

Phase 1 must land first (everything depends on the converters, resolver, and the bridge). Phases 2–4 are then largely independent, with **one cross-phase data dependency**: `/positions.avgPrice` and `/data/trades` (Phase 4) consume the *enriched* trades ledger; `/last-trade-price` (Phase 3) reads only raw trade columns (§8.7) and so does not depend on the Phase-4 enrichment. Phase 5 depends on all of 1–4 (it targets their final endpoint shapes) and so runs last.

---

## 11. Testing strategy

Follow the existing idiom: `pytest`, `TestClient(app)`, the autouse fresh `:memory:` DB fixture (`tests/conftest.py`), the `_seed_market`/register helpers. For each migrated endpoint:

1. **Shape contract test** — assert the response JSON matches the Polymarket shape exactly: field names present, types correct (decimal-string vs float vs int per §4), no leftover agentpit fields, correct casing.
2. **Round-trip test** — seed market → place order(s) via `POST /order` → assert `/data/orders`, `/book`, `/data/trades`, `/positions`, `/activity` reflect it with consistent values across endpoints.
3. **Converter unit tests** — `price_to_decimal_str(360000) == "0.36"`, size/float variants, inverses.
4. **Cancel semantics** — `DELETE /order` on a missing id returns 200 with the id in `not_canceled`.
5. **Bridge test** — `GET /markets?polymarket_condition_id=…` returns the right market with `clobTokenIds`.
6. **Secret-safety test** — assert no response body ever contains a value usable as a bearer api_key; specifically that `owner` (top-level and in `/data/trades` `maker_orders[].owner`, including a *counterparty's*) is a `USER_ID`, not an api_key.

Cross-check shapes against the live Polymarket OpenAPI via the docs MCP (`docs.polymarket.com/mcp`) during implementation. UI: rely on the TS type layer (`ui/src/types/*`) — changing a type cascades compile errors at every stale consumer (good coverage).

---

## 12. Acceptance criteria

1. Every migrated endpoint at §5 responds at its **Polymarket path** with **Polymarket-exact JSON** (verified field-by-field against the docs-MCP OpenAPI for that endpoint).
2. The old agentpit-flavored trading endpoints are **removed**; nothing serves both *response shapes/paths*. (The transitional `market_id`+`outcome` request fallback on `POST /order` is a request-only convenience, removed at the end of Phase 2 — §8.1.)
3. A user can: place an order (`POST /order`), see it in `/data/orders` and `/book`, get filled, and see the fill in `/data/trades` and `/activity`, with `/positions`, `/value`, and `/balance-allowance` consistent — all in Polymarket shapes.
4. The bridge resolves a Polymarket `conditionId` to an agentpit market with usable `clobTokenIds`.
5. The agentpit UI works end-to-end against the migrated API (no console/runtime errors; orderbook, sparkline, order ticket, portfolio all render).
6. `split`/`merge`/`redeem` and all agentpit-native endpoints are unchanged and still pass their tests.
7. `pytest` green; no new diagnostics in changed files.

---

## 13. Decisions log

- **Full switch, in place** (not a parallel layer): single Polymarket-shaped surface in `agentpit/api/`; UI migrated in lockstep. Rationale: kill the two-surface ambiguity.
- **Match Polymarket exactly per endpoint** (casing + representation), superseding blanket snake_case.
- **Requests use logical order args; no EIP-712/L2 HMAC** — deferred (§2).
- **Gamma = practical ~20-field subset**, exact-shaped.
- **`split`/`merge`/`redeem` stay native**; effects surface in `/activity`.
- **`outcome` matching stays case-insensitive**, documented.
- **IDs stay backend-specific**; bot translates via the bridge.
- **`owner` in responses = the non-secret `USER_ID`, never the api_key** (which is agentpit's bearer credential) — most critically the counterparty's `owner` inside `/data/trades` `maker_orders`. Internal `*_API_KEY` filter columns are never serialized.
- **Status enums use the unprefixed live form**; agentpit emits only `live`/`matched` (place) and `MATCHED`/`CONFIRMED`/`FAILED` (read). `delayed`/`unmatched` are documented but unreachable.
- **Wire envelopes**: `/data/orders` returns a bare `OpenOrder[]`; `/data/trades` returns the `{limit,count,next_cursor,data}` envelope; cursor pagination is otherwise deferred.
- **Data-API reads (`/positions`/`/value`/`/activity`) are public-by-address**; CLOB reads stay auth-filtered.

## 14. Out of scope (this spec)

L2 HMAC auth, EIP-712 signed-order intake, full Gamma fidelity, WebSocket parity, batch `POST /orders`, official-SDK drop-in. See §2.
