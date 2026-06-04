# Phase 4 — Fills, Positions, Balance, Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Migrate agentpit's account-data reads to Polymarket's exact interfaces — CLOB `GET /data/trades` (fills) + `GET /balance-allowance`, Data-API `GET /positions` (+`/value`) + `GET /activity` — backed by an owner-attributed `trades` ledger, and wire `SPLIT`/`MERGE`/`REDEEM` logging (missing-feature #01). Rework the portfolio UI in lockstep.

**Architecture:** The `trades` table gains owner attribution (`TAKER_API_KEY`/`MAKER_API_KEY`, internal filter keys never serialized) and stores `MARKET` = condition_id; `_insert_trade` enriches the `MAKER_ORDERS` JSON to the full Polymarket `MakerOrder` shape (`owner` = non-secret USER_ID, separate `maker_address` = eth `MAKER`). A single match serializes from both the taker's and a maker's perspective (`trader_side` toggles) at read time. CLOB reads (`/data/trades`, `/balance-allowance`) stay auth-filtered to the calling api_key. Data-API reads (`/positions`, `/value`, `/activity`) are **public-by-address** — `user` is an agentpit eth address, no auth. PnL/pricing on `/positions` derive from the user's fills (avgPrice) + the book midpoint (curPrice), with defensible defaults where unavailable.

**Tech Stack:** FastAPI, Pydantic v2, raw `sqlite3`, pytest + `TestClient` (+ live-chain `tests/onchain/`), React + TS UI.

**Spec:** `docs/superpowers/specs/2026-06-03-agentpit-polymarket-api-migration-design.md` §7, §8.4, §8.8–8.10, §8.12, §9, §13.

**Representation (§4):** CLOB (`/data/trades`, `/balance-allowance`): decimal/base-unit **strings**. Data-API (`/positions`, `/value`, `/activity`): **floats** + **int-seconds**. Converters in `agentpit.polymarket.format`: `price_to_decimal_str`/`price_to_float`, `size_to_decimal_str`/`size_to_float`. `_PRICE_ONE = 10**6`.

**Identity / secret-safety (§13):** `owner` on every wire object is the non-secret **USER_ID**, never the api_key. `TAKER_API_KEY`/`MAKER_API_KEY` are internal filter columns only — never serialized.

**Current code:**
- `trades` table (`table_create.py:create_trades_table`): `TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID, PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS, MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS`. **`MARKET` currently holds the token_id** (bug per §7) and there are no api_key columns.
- `OrderService._insert_trade` (order_service.py ~706): writes the row; `MAKER_ORDERS=[{order_id, owner: maker MAKER, matched_amount}]`; `MARKET=ASSET_ID=taker TOKEN_ID`. Returns `trade_id` (Phase 2).
- `TableWrite.log_transaction(db, api_key, transaction_type, market_id, details)` (table_write.py ~366): inserts a `transactions` row — **never called** today.
- `PositionService.split/merge/redeem` (position_service.py): on-chain CTF ops, no DB transaction log.
- `PortfolioService.get_portfolio(user, market_id)` → `PortfolioResponse{eth_address, usdc_balance:int, positions:[Position{market_id, question, token_id, outcome_label, outcome_index, balance:int}]}`.
- `UsdcService.get_balance(user)` → `{eth_address, balance:int}`.
- Routes: `GET /portfolio` + `GET /transactions` (portfolio.py); `GET /usdc_balance` (usdc.py); split/merge/redeem (positions.py). Data-API reads will live in a new `routes/data_api.py`.

---

## File Structure

**Create:**
- `agentpit/datastructures/trade_wire.py` — `TradeWire`, `MakerOrderWire` (CLOB `/data/trades`).
- `agentpit/datastructures/position_wire.py` — `PositionWire` (Data-API `/positions`).
- `agentpit/datastructures/activity_wire.py` — `ActivityWire` (Data-API `/activity`).
- `agentpit/datastructures/balance_allowance.py` — `BalanceAllowanceResponse`.
- `agentpit/services/trade_service.py` — `/data/trades` read.
- `agentpit/services/account_service.py` — `/positions`, `/value`, `/activity` (public-by-address).
- `agentpit/api/routes/data_api.py` — Data-API routes (`/positions`, `/value`, `/activity`).
- Tests: `tests/onchain/test_data_trades.py`, `tests/onchain/test_positions.py`, `tests/onchain/test_activity.py`, `tests/api/test_balance_allowance.py`.

**Modify:**
- `agentpit/db/table_create.py` — add `TAKER_API_KEY`/`MAKER_API_KEY` columns (idempotent migration) to `trades`.
- `agentpit/db/table_read.py` — `get_user_id_by_api_key`; trade/activity read queries.
- `agentpit/services/order_service.py` — enrich `_insert_trade` (condition_id MARKET, api_key columns, full MakerOrder shape).
- `agentpit/services/position_service.py` — wire `log_transaction` in split/merge/redeem.
- `agentpit/services/usdc_service.py` — `get_balance_allowance`.
- `agentpit/api/routes/usdc.py` → replace `/usdc_balance` with `/balance-allowance` (rename file to `balance.py` or keep; see Task 4).
- `agentpit/api/routes/portfolio.py` — remove `/portfolio` + `/transactions` (replaced by Data-API).
- `agentpit/api/app.py` — register `data_api` router; drop the `portfolio` router if emptied.
- `agentpit/api/deps.py` — add `TradeServiceDep`, `AccountServiceDep`.
- UI: `ui/src/api/portfolio.ts`, `ui/src/pages/ProfilePage.tsx`, `ui/src/components/orders/OrderTicket.tsx`.

**Do NOT touch:** `agentpit_bots/`, `tests/bots/`, `scripts/seed_market_orders.py` (Phase 5).

---

## Task 1: `trades` ledger owner-attribution (foundation)

**Files:**
- Modify: `agentpit/db/table_create.py`, `agentpit/db/table_read.py`, `agentpit/services/order_service.py`
- Test: `tests/onchain/test_trade_enrichment.py` (create)

§7: add `TAKER_API_KEY`/`MAKER_API_KEY` (internal), store `MARKET` = condition_id, enrich `MAKER_ORDERS` to the full `MakerOrder` shape (`owner` flips from eth `MAKER` to USER_ID; add `maker_address` = `MAKER`).

- [ ] **Step 1: Idempotent column migration**

In `agentpit/db/table_create.py`, find where additive migrations live (the existing `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` pattern). Add a migration that adds `TAKER_API_KEY TEXT` and `MAKER_API_KEY TEXT` to `trades` if absent. If there's a `_migrate`/`ensure_columns` helper, follow it; otherwise add to `create_trades_table` after the `CREATE TABLE`:
```python
        existing = {r[1] for r in db.execute("PRAGMA table_info(trades)").fetchall()}
        for col in ("TAKER_API_KEY", "MAKER_API_KEY"):
            if col not in existing:
                db.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
```

- [ ] **Step 2: `get_user_id_by_api_key` helper**

In `agentpit/db/table_read.py` add:
```python
    @staticmethod
    def get_user_id_by_api_key(db: sqlite3.Connection, api_key: str) -> str | None:
        row = db.execute(
            "SELECT USER_ID FROM users WHERE API_KEY = ? LIMIT 1", (api_key,)
        ).fetchone()
        return row[0] if row else None
```

- [ ] **Step 3: Enrich `_insert_trade`**

In `agentpit/services/order_service.py`, rewrite `_insert_trade` to resolve condition_id + user ids and store the full shape. It currently is a `@staticmethod`; keep it static (it has `conn`). The taker's api_key is `taker_row["API_KEY"]`; the maker row is `match["maker_row"]` (a full `orders` row with `API_KEY` and `MAKER`). Replace the method body:
```python
    @staticmethod
    def _insert_trade(
        conn: sqlite3.Connection, taker_row: sqlite3.Row, match: dict
    ) -> str:
        trade_id = "{}-{}-{}".format(
            taker_row["ORDER_ID"], match["maker_order_id"], secrets.token_hex(8)
        )
        token_id = taker_row["TOKEN_ID"]
        resolved = resolve_by_token_id(conn, token_id)
        condition_id = resolved.condition_id if resolved else token_id
        outcome_label = (
            resolved.market.erc1155_tokens[resolved.outcome_index][1]
            if resolved else ""
        )
        maker_row = match["maker_row"]
        maker_user_id = TableRead.get_user_id_by_api_key(conn, maker_row["API_KEY"])
        maker_side = maker_row["SIDE"]
        maker_orders_payload = [
            {
                "order_id": match["maker_order_id"],
                "owner": maker_user_id or "",        # non-secret USER_ID (§13)
                "maker_address": maker_row["MAKER"],  # eth address
                "matched_amount": str(match["trade_size"]),
                "price": int(match["price"]),
                "fee_rate_bps": int(maker_row["FEE_RATE_BPS"]),
                "asset_id": token_id,
                "outcome": outcome_label,
                "side": maker_side,
            }
        ]
        conn.execute(
            """
            INSERT INTO trades (
                TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
                PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS,
                MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS,
                TAKER_API_KEY, MAKER_API_KEY
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                taker_row["ORDER_ID"],
                json.dumps(maker_orders_payload),
                condition_id,                 # MARKET = condition_id (§7 fix)
                token_id,                     # ASSET_ID = token_id
                match["price"],
                match["trade_size"],
                taker_row["REMAINING_AMOUNT"],
                taker_row["SIDE"],
                "PENDING",
                int(datetime.now(timezone.utc).timestamp()),
                "",
                0,
                int(taker_row["FEE_RATE_BPS"]),
                taker_row["API_KEY"],          # internal filter key (never serialized)
                maker_row["API_KEY"],          # internal filter key
            ),
        )
        return trade_id
```
(`resolve_by_token_id` and `TableRead` are already imported in this module.)

- [ ] **Step 4: Test the enrichment**

Create `tests/onchain/test_trade_enrichment.py` — produce a settled NORMAL match (mirror `tests/onchain/test_trade_flow.py::test_match_settles_on_chain`: A BUY YES @0.6 maker via `user_split_position` to fund B's YES, B SELL YES @0.6 taker), then read the `trades` row directly via `DbSession`:
```python
"""trades ledger owner-attribution (§7): MARKET=condition_id, api_key columns
populated, MAKER_ORDERS carries USER_ID owner + maker_address."""

import json
import secrets
import uuid

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from fastapi.testclient import TestClient


def _hdr(t): return {"Authorization": f"Bearer {t}"}
def _email(): return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


def test_trade_row_is_owner_attributed():
    app = create_app()
    client = TestClient(app)
    a_email, b_email = _email(), _email()
    ra = client.post("/register", json={"email": a_email, "password": "hunter22hunter22"}).json()
    rb = client.post("/register", json={"email": b_email, "password": "hunter22hunter22"}).json()
    ta, tb = ra["access_token"], rb["access_token"]
    a_uid, b_uid = ra["user"]["user_id"], rb["user"]["user_id"]
    a_addr = ra["user"]["eth_address"]

    market = client.post("/markets", json={
        "question": f"Enrich {secrets.token_hex(4)}?", "description": "x",
        "outcome_labels": ["YES", "NO"]}).json()
    yes = market["erc1155_tokens"][0][0]
    cond = market["condition_id"]["value"]

    # Fund B with YES so it can SELL into A's resting BUY.
    settings = Settings()
    d = Deployment.load(settings.deployment_path)
    w = Web3Client(settings, d); c = Contracts(w.web3, d); admin = OnchainAdmin(w, c)
    db = DbSession(settings.db_path)
    with db.read() as conn:
        user_b = TableRead.get_user_by_email(conn, b_email)
    admin.user_split_position(user_b.eth_key, bytes.fromhex(cond[2:]), 200_000_000)

    client.post("/order", headers=_hdr(ta), json={"token_id": yes, "side": "BUY", "price": "0.6", "size": 100})
    client.post("/order", headers=_hdr(tb), json={"token_id": yes, "side": "SELL", "price": "0.6", "size": 100})

    with db.read() as conn:
        conn.row_factory = __import__("sqlite3").Row
        row = conn.execute(
            "SELECT * FROM trades WHERE ASSET_ID = ? ORDER BY MATCH_TIME DESC LIMIT 1",
            (yes,),
        ).fetchone()
    assert row["MARKET"] == cond                      # condition_id, not token_id
    assert row["ASSET_ID"] == yes
    # Taker is B (SELL), maker is A (BUY).
    makers = json.loads(row["MAKER_ORDERS"])
    assert makers[0]["owner"] == a_uid                # USER_ID, not eth or api_key
    assert makers[0]["maker_address"].startswith("0x")
    assert makers[0]["asset_id"] == yes
    # Internal api-key filter columns are populated (taker=B, maker=A) but are
    # never part of any wire response (asserted in Task 2).
    assert row["TAKER_API_KEY"] and row["MAKER_API_KEY"]
    assert row["TAKER_API_KEY"] != row["MAKER_API_KEY"]
```
Run: `.venv/bin/python -m pytest tests/onchain/test_trade_enrichment.py -v` → PASS. Also run `tests/onchain/test_trade_flow.py` (the existing trades-touching test) to confirm no regression.

- [ ] **Step 5: Commit**
```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py agentpit/services/order_service.py tests/onchain/test_trade_enrichment.py
git commit -m "feat(trades): owner-attribute ledger (MARKET=condition_id, USER_ID maker owner, api_key cols)"
```

---

## Task 2: `GET /data/trades` (fills, CLOB)

**Files:**
- Create: `agentpit/datastructures/trade_wire.py`, `agentpit/services/trade_service.py`, `tests/onchain/test_data_trades.py`
- Modify: `agentpit/api/deps.py`, `agentpit/api/routes/orders.py` (or a CLOB route module), `agentpit/db/table_read.py`

**Contract (§8.4):** auth-filtered to the user as **taker OR maker**. Raw HTTP envelope `{limit, count, next_cursor, data: Trade[]}` with `next_cursor` = `"LTE="` when unpaged. `Trade` fields (all strings except `bucket_index:int`): `id, taker_order_id, market(condition_id), asset_id(token_id), side, size, fee_rate_bps, price, status, match_time, last_update, outcome, bucket_index, owner(USER_ID), maker_address, maker_orders:[MakerOrder], transaction_hash, trader_side`. `status` maps `PENDING`/settled→`MATCHED`/`CONFIRMED`, `FAILED`→`FAILED`. `trader_side` = `TAKER` when the querying user owns the taker order, else `MAKER`.

- [ ] **Step 1: `TradeWire`/`MakerOrderWire` models**

`agentpit/datastructures/trade_wire.py`:
```python
from pydantic import BaseModel, Field


class MakerOrderWire(BaseModel):
    order_id: str
    owner: str            # USER_ID
    maker_address: str
    matched_amount: str   # decimal shares
    price: str
    fee_rate_bps: str
    asset_id: str
    outcome: str
    side: str


class TradeWire(BaseModel):
    id: str
    taker_order_id: str
    market: str           # condition_id
    asset_id: str         # token_id
    side: str
    size: str             # decimal shares
    fee_rate_bps: str
    price: str
    status: str
    match_time: str       # unix seconds, stringified
    last_update: str
    outcome: str
    bucket_index: int
    owner: str            # USER_ID
    maker_address: str
    maker_orders: list[MakerOrderWire] = Field(default_factory=list)
    transaction_hash: str
    trader_side: str      # TAKER | MAKER


class TradesEnvelope(BaseModel):
    limit: int = 100
    count: int = 0
    next_cursor: str = "LTE="
    data: list[TradeWire] = Field(default_factory=list)
```

- [ ] **Step 2: `TableRead` query** — add a method returning the user's trade rows (taker OR maker) with optional `market`/`asset_id`/`id`/`maker_address`/`before`/`after` filters, ordered by `MATCH_TIME DESC`. Filter `WHERE (TAKER_API_KEY = ? OR MAKER_API_KEY = ?)` + dynamic clauses. Return raw `sqlite3.Row` dicts.

- [ ] **Step 3: `TradeService.list_trades`** — for each row, compute `trader_side` (`TAKER` if `row["TAKER_API_KEY"] == user.api_key` else `MAKER`); the top-level `owner` is the querying user's USER_ID, `maker_address` is the user's eth `MAKER` for their side; `side`/`outcome` from the row; `size`=`size_to_decimal_str(TRADE_SIZE)`; `price`=`price_to_decimal_str(PRICE)`; `status` mapped (`PENDING`/settled→`MATCHED`, `FAILED`→`FAILED` — agentpit has no separate CONFIRMED state, so emit `MATCHED` for non-failed); `match_time`/`last_update`=`str(MATCH_TIME)`; `maker_orders` parsed from JSON → `MakerOrderWire[]` (the stored `price`/`fee_rate_bps` ints → strings, `matched_amount` micro→`size_to_decimal_str`). Return `TradesEnvelope`. **Never read or emit any api_key.**

- [ ] **Step 4: Route + dep** — add `TradeServiceDep` in `deps.py`; add `GET /data/trades` (auth) with query params `market`, `asset_id`, `id`, `maker_address`, `before`, `after`, `next_cursor` → `TradesEnvelope`. Put it next to `/data/orders` (orders.py) or a new CLOB module.

- [ ] **Step 5: Test** (`tests/onchain/test_data_trades.py`) — settled NORMAL match (A maker, B taker). Assert: B's `GET /data/trades` returns one trade with `trader_side == "TAKER"`, `market == cond`, `size == "100"`, `price == "0.6"`, `status == "MATCHED"`, `owner == b_user_id`; A's `GET /data/trades` returns the SAME match with `trader_side == "MAKER"`. **Secret-safety:** assert the full JSON text of both responses contains neither api_key (fetch each user's api_key is not exposed — instead assert `owner` equals the expected USER_ID and that no value in the body equals the bearer token). Run → PASS.

- [ ] **Step 6: Commit** `feat(trades): GET /data/trades returns CLOB Trade[] (dual-perspective)`

---

## Task 3: `GET /positions` + `GET /value` (Data-API, public-by-address)

**Files:**
- Create: `agentpit/datastructures/position_wire.py`, `agentpit/services/account_service.py`, `agentpit/api/routes/data_api.py`, `tests/onchain/test_positions.py`
- Modify: `agentpit/api/deps.py`, `agentpit/api/app.py`, `agentpit/db/table_read.py`

**Contract (§8.8/8.9):** public-by-address (`user` = eth address, **no auth**); resolve the eth address → user. `GET /positions?user=&market=` → array of `PositionWire` (floats). `GET /value?user=` → `[{user, value}]` (total MTM float). Pricing: `avgPrice` from the user's fills (the enriched trades ledger); `curPrice` from the book midpoint (reuse `OrderService.get_midpoint`/`_best_bid_ask`, fall back to last trade or `0.5`); derive `initialValue`/`currentValue`/`cashPnl`/`percentPnl`. Use defensible defaults (`0.0`) where unavailable — the shape stays exact.

- [ ] **Step 1: `PositionWire` model** — fields (floats unless noted): `proxyWallet`(eth), `asset`(token_id), `conditionId`, `size`, `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `percentPnl`, `totalBought`, `realizedPnl`, `percentRealizedPnl`, `curPrice`, `redeemable`(bool), `title`, `slug`, `icon`, `eventSlug`, `outcome`, `outcomeIndex`(int), `oppositeOutcome`, `oppositeAsset`, `endDate`, `negativeRisk`(bool). Give every field a default so partial data still validates.

- [ ] **Step 2: `AccountService`** — `__init__(db, onchain)`. `list_positions(eth_address, market=None)`:
  - resolve eth_address → user (`TableRead.get_user_by_eth_address`; add it if missing — `SELECT ... WHERE ETH_ADDRESS = ?`). If unknown → return `[]`.
  - reuse the `PortfolioService` balance scan (or inline: list markets, `onchain.ctf_balance`) to get held `(market, token_id, outcome_index, balance)`.
  - for each holding: `size = balance/1e6`; `avgPrice` = volume-weighted price of the user's BUY fills for that `asset_id` from `trades` (taker or maker, non-FAILED) — `sum(price*size)/sum(size)` in dollars, else `0.0`; `curPrice` = midpoint of the token's book (`(best_bid+best_ask)/2` via the order rows; fall back to the token's last trade price, else `0.5`); `initialValue=avgPrice*size`; `currentValue=curPrice*size`; `cashPnl=currentValue-initialValue`; `percentPnl = cashPnl/initialValue*100 if initialValue else 0.0`; `totalBought=initialValue`; `redeemable = market RESOLVED and this outcome is the winner`; `oppositeAsset`/`oppositeOutcome` = the complement token/label; `title/slug/icon/endDate` from the market; `conditionId`=market condition_id. Defaults elsewhere `0.0`/`""`/`false`.
  - `market` filter: only holdings whose condition_id is in the provided csv.
  - `total_value(eth_address)` = sum of `currentValue` → `[{"user": eth_address, "value": total}]`.

- [ ] **Step 3: Routes** (`agentpit/api/routes/data_api.py`, new router, NO auth):
```python
@router.get("/positions", response_model=list[PositionWire])
def get_positions(user: str, service: AccountServiceDep, market: str | None = None): ...
@router.get("/value")
def get_value(user: str, service: AccountServiceDep) -> list[dict]: ...
```
Register `data_api.router` in `app.py`.

- [ ] **Step 4: Test** (`tests/onchain/test_positions.py`) — register A, fund + place a BUY that fills (mirror the settled-match setup) so A holds YES; `GET /positions?user=<A eth>` → one position with `asset == yes_token`, `conditionId == cond`, `size == 100.0`, `outcome == "YES"`, `avgPrice` ≈ 0.6, `curPrice` a float; `GET /value?user=<A eth>` → `[{"user": <addr>, "value": <float>}]`. Unknown address → `[]`. **No auth header** is sent. Run → PASS.

- [ ] **Step 5: Commit** `feat(positions): GET /positions + /value (Data-API, public-by-address)`

---

## Task 4: `GET /balance-allowance` (CLOB)

**Files:**
- Modify: `agentpit/services/usdc_service.py`, `agentpit/api/routes/usdc.py`, `agentpit/datastructures/balance_allowance.py` (create)
- Test: `tests/onchain/test_balance_allowance.py` (create)

**Contract (§8.12):** `GET /balance-allowance?asset_type=COLLATERAL|CONDITIONAL&token_id=&signature_type=` → `{ "balance": "<base-unit int string>", "allowances": {} }`. `COLLATERAL`→USDC balance; `CONDITIONAL` (requires `token_id`)→CTF outcome-token balance. `signature_type` accepted and ignored. Replaces `GET /usdc_balance`.

- [ ] **Step 1: Model** — `agentpit/datastructures/balance_allowance.py`:
```python
from pydantic import BaseModel, Field


class BalanceAllowanceResponse(BaseModel):
    """Raw CLOB BalanceAllowanceResponse (§8.12). `balance` is a base-unit
    integer string; agentpit tracks no allowances → empty map."""

    balance: str
    allowances: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 2: Service** — replace `get_balance` with:
```python
    def get_balance_allowance(
        self, user: User, asset_type: str, token_id: str | None
    ) -> BalanceAllowanceResponse:
        if asset_type == "CONDITIONAL":
            if not token_id:
                raise MarketStateError("token_id required for CONDITIONAL")
            bal = self._onchain.ctf_balance(user.eth_address, int(token_id))
        else:  # COLLATERAL
            bal = self._onchain.usd_balance(user.eth_address)
        return BalanceAllowanceResponse(balance=str(bal))
```
(import `MarketStateError`, `BalanceAllowanceResponse`.)

- [ ] **Step 3: Route** — in `agentpit/api/routes/usdc.py` replace the handler:
```python
@router.get("/balance-allowance", response_model=BalanceAllowanceResponse)
def get_balance_allowance(
    user: CurrentUserDep,
    service: UsdcServiceDep,
    asset_type: str = "COLLATERAL",
    token_id: str | None = None,
    signature_type: int | None = None,   # accepted, ignored (§2)
) -> BalanceAllowanceResponse:
    return service.get_balance_allowance(user, asset_type, token_id)
```
(Remove the old `GetUsdcBalanceResponse` import/route; delete `get_usdc_balance_response.py` if now unused.)

- [ ] **Step 4: Test** (`tests/onchain/test_balance_allowance.py`) — register a user (auto-funded with the signup grant); `GET /balance-allowance` (default COLLATERAL) → `{"balance": "<grant>", "allowances": {}}` (balance is a numeric string == the signup grant raw); `GET /balance-allowance?asset_type=CONDITIONAL&token_id=<yes>` → `{"balance": "0", "allowances": {}}` (no tokens held); CONDITIONAL without token_id → 400. Run → PASS.

- [ ] **Step 5: Commit** `feat(balance): GET /balance-allowance replaces /usdc_balance`

---

## Task 5: `GET /activity` + wire SPLIT/MERGE/REDEEM (Data-API)

**Files:**
- Modify: `agentpit/services/position_service.py`, `agentpit/services/account_service.py`, `agentpit/api/routes/data_api.py`, `agentpit/api/routes/portfolio.py`, `agentpit/api/app.py`, `agentpit/db/table_read.py`
- Create: `agentpit/datastructures/activity_wire.py`, `tests/onchain/test_activity.py`

**Contract (§8.10):** public-by-address. `GET /activity?user=&type=&market=&limit=&offset=&start=&end=&side=` → array of `ActivityWire` (floats, int-seconds): `proxyWallet, timestamp(int), conditionId, type, size, usdcSize, transactionHash, price, asset, side, outcomeIndex, title, slug, icon, eventSlug, outcome, name, pseudonym, bio, profileImage, profileImageOptimized`. `TRADE` rows from the user's fills (trades ledger); `SPLIT`/`MERGE`/`REDEEM` rows from the `transactions` table. Profile fields default `""`/`null`.

- [ ] **Step 1: Wire `log_transaction` into split/merge/redeem.** In `PositionService.split`/`merge`/`redeem`, after the on-chain op succeeds, write a transaction row. These services hold `user` (with `api_key`) but currently only do `self._db.read()` for the market — add a `self._db.write()` to call `TableWrite.log_transaction(conn, user.api_key, "SPLIT"|"MERGE"|"REDEEM", market_id, {"amount": ...})`. Import `TableWrite`. (For `redeem`, log `{"collateral_amount": ...}`.)

- [ ] **Step 2: `ActivityWire` model** — all the §8.10 fields with defaults (floats `0.0`, ints `0`, strings `""`, profile fields `""`).

- [ ] **Step 3: `AccountService.list_activity(eth_address, type=None, market=None, ...)`** — resolve eth→user; if unknown → `[]`. Build `TRADE` activities from the user's `trades` (per fill: `type="TRADE"`, `timestamp=MATCH_TIME`, `conditionId=MARKET`, `asset=ASSET_ID`, `side`, `price=price_to_float`, `size=size_to_float(TRADE_SIZE)`, `usdcSize=price*size`, `transactionHash`, `outcome`/`outcomeIndex`/`title`/`slug`/`icon` from the market). Build `SPLIT`/`MERGE`/`REDEEM` activities from `transactions` (per row: `type=TRANSACTION_TYPE`, `timestamp`, `conditionId` from market_id→market, `size`/`usdcSize` from `details.amount`). Filter by `type` (csv) and `market`. Sort by `timestamp DESC`, apply `limit`/`offset`. Profile fields `""`.

- [ ] **Step 4: Route** — `GET /activity` in `data_api.py` (no auth) → `list[ActivityWire]`. **Remove `GET /transactions` and `GET /portfolio`** from `portfolio.py` (both replaced — `/portfolio` by `/positions`, `/transactions` by `/activity`); if `portfolio.py` is now empty, drop its router from `app.py` and delete the file. (The UI still calls `/portfolio` until Task 6 — that's the transient-red window; the Python suite doesn't cover the UI.)

- [ ] **Step 5: Test** (`tests/onchain/test_activity.py`) — register A, do a `split_position` (logs SPLIT) and a settled BUY (logs a TRADE fill); `GET /activity?user=<A eth>` → contains a `{"type":"SPLIT", ...}` and a `{"type":"TRADE", ...}` row with float `size`/`price`, int `timestamp`, `conditionId==cond`; `?type=SPLIT` filters to just the split. Unknown address → `[]`. No auth header. Run → PASS.

- [ ] **Step 6: Commit** `feat(activity): GET /activity + SPLIT/MERGE/REDEEM logging; drop /portfolio,/transactions`

---

## Task 6: UI — portfolio → positions

**Files:**
- Modify: `ui/src/api/portfolio.ts`, `ui/src/pages/ProfilePage.tsx`, `ui/src/components/orders/OrderTicket.tsx`

The UI's authenticated user views their own holdings; call `/positions?user=<own eth address>` (the address is on the auth'd user object). Read each file fully first.

- [ ] **Step 1: `api/portfolio.ts`** — replace `getPortfolio()`/`PortfolioResponse` with `getPositions(userAddress)` returning `Position[]` (the `PositionWire` shape: `asset`, `conditionId`, `size:number`, `avgPrice`, `curPrice`, `outcome`, `outcomeIndex`, `title`, `cashPnl`, …). `usePositions(userAddress)` keyed `["positions", userAddress]`. (Balance now comes from `/balance-allowance` — add a `getBalance()` → `Number(balance)/1e6` helper if the UI shows USDC.)

- [ ] **Step 2: `ProfilePage.tsx`** — consume `usePositions(user.eth_address)`; map `size` (already display shares — drop the `/SHARES_SCALE`), show `avgPrice`/`curPrice`/`cashPnl`. Replace the old `usdc_balance` read with `/balance-allowance`.

- [ ] **Step 3: `OrderTicket.tsx`** — the `heldByOutcome` map currently reads `usePortfolio().positions[].balance / PORTFOLIO_SHARES_SCALE` keyed by `outcome_label`/`market_id`. Switch to `usePositions(user.eth_address)`, key by `outcome`, value `size` (already display shares — remove `PORTFOLIO_SHARES_SCALE` and the `/1e6`). Filter to the current `marketId` via `conditionId` (resolve the market's condition_id) or by `asset` (token id) membership in the market's `erc1155_tokens`.

- [ ] **Step 4: Build** — `cd ui && npm run build` (typecheck) + `npx vitest run` → green. Grep `src/` for `getPortfolio`, `usePortfolio`, `usdc_balance`, `PORTFOLIO_SHARES_SCALE` and reconcile.

- [ ] **Step 5: Commit** `feat(ui): portfolio reads /positions (+ /balance-allowance)`

---

## Final verification

- [ ] **Full suite**: `.venv/bin/python -m pytest -q -p no:cacheprovider` → all pass.
- [ ] **UI**: `cd ui && npm run build && npx vitest run` → green.
- [ ] **No dangling refs**: `grep -rn "/portfolio\b\|/transactions\b\|/usdc_balance\|get_portfolio\|usePortfolio\|GetUsdcBalanceResponse\|TransactionHistoryResponse" agentpit/ ui/src/ | grep -v node_modules` → no hits in migrated code (`agentpit_bots/`/`scripts/` are Phase 5).
- [ ] **Secret-safety sweep**: confirm no response body (`/data/trades`, `/positions`, `/activity`) serializes an api_key; `owner` is always a USER_ID.
- [ ] **Final whole-phase review** (subagent-driven-development), then checkpoint before Phase 5.

---

## Notes for the implementer

- **Run Python via `.venv/bin/python`.** On-chain tests need the forked anvil + deployed stack (already up). Settled-trade tests follow the `tests/onchain/test_trade_flow.py::test_match_settles_on_chain` funding pattern (B funded via `admin.user_split_position`).
- **Cross-check shapes** against the live Polymarket OpenAPI via the docs MCP (`docs.polymarket.com/mcp`) — especially the `/data/trades` `Trade`/`MakerOrder` field set, the `/positions` field set, and `/activity`.
- **Secret-safety (§13) is paramount this phase**: `TAKER_API_KEY`/`MAKER_API_KEY` are internal filter columns — never serialize them; every wire `owner` is a USER_ID. The dual-perspective `/data/trades` surfaces a *counterparty's* `owner` — it must be their USER_ID, not their api_key.
- **Data-API endpoints are public-by-address** (no auth); **CLOB endpoints** (`/data/trades`, `/balance-allowance`) stay auth-filtered.
- **Internal consumers out of scope** (Phase 5): do not edit `agentpit_bots/`, `tests/bots/`, `scripts/seed_market_orders.py`.
- After editing, report new LSP/TS diagnostics in changed files and fix them.
