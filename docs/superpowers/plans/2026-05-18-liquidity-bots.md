# Liquidity Bots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that anchors AgentPit prices to Polymarket and keeps order books alive with two strategies: a per-market anchor market-maker and a small pool of noise traders.

**Architecture:** Standalone external service (`agentpit_bots/`) that authenticates against AgentPit as ordinary registered users via JWT and uses the public REST API. Reads Polymarket midpoints via the public CLOB endpoints. Server-side changes are limited to a small schema migration, a new admin endpoint to flag bot users, and a new endpoint for a user to list their own live orders.

**Tech Stack:** Python 3.10+, FastAPI (server), SQLite, `py_clob_client` (Polymarket reads), `requests` (bot → AgentPit), pytest.

**Spec:** [docs/superpowers/specs/2026-05-18-liquidity-bots-design.md](../specs/2026-05-18-liquidity-bots-design.md)

---

## File Map

**Server-side (modify):**
- `agentpit/db/table_create.py` — add `MARKETS.POLYMARKET_YES_TOKEN_ID`, `MARKETS.POLYMARKET_NO_TOKEN_ID`, `USERS.IS_BOT` migrations
- `agentpit/datastructures/market.py` — add the two upstream token id fields
- `agentpit/datastructures/create_market_request.py` — same
- `agentpit/datastructures/user.py` — add `is_bot: bool` field
- `agentpit/db/table_write.py` — write the new columns; add `mark_user_as_bot(api_key)`
- `agentpit/db/table_read.py` — return new columns; add `list_live_orders_for_user(api_key)`
- `agentpit/polymarket/polymarket_sync.py` — capture upstream tokens *before* the local CTF overwrite
- `agentpit/services/order_service.py` — add `list_live_orders(user) -> list[dict]`
- `agentpit/api/routes/orders.py` — add `GET /orders/mine`
- `agentpit/config.py` — add `admin_token: str` setting

**Server-side (create):**
- `agentpit/api/routes/admin.py` — `POST /admin/mark_bot`
- `agentpit/api/app.py` — register the admin router (modify, treated as create-section-of-file)

**Bot service (create):**
- `agentpit_bots/__init__.py`
- `agentpit_bots/config.py`
- `agentpit_bots/client.py`
- `agentpit_bots/price_oracle.py`
- `agentpit_bots/reconcile.py`
- `agentpit_bots/strategies/__init__.py`
- `agentpit_bots/strategies/base.py`
- `agentpit_bots/strategies/anchor_mm.py`
- `agentpit_bots/strategies/noise_trader.py`
- `agentpit_bots/bot_pool.py`
- `agentpit_bots/runner.py`
- `agentpit_bots/creds.json` — gitignored (created at runtime)

**Tests (create):**
- `tests/api/test_admin.py`
- `tests/api/test_orders_mine.py`
- `tests/api/test_polymarket_token_ids.py`
- `tests/bots/__init__.py`
- `tests/bots/conftest.py`
- `tests/bots/test_reconcile.py`
- `tests/bots/test_price_oracle.py`
- `tests/bots/test_client.py`
- `tests/bots/test_anchor_mm.py`
- `tests/bots/test_noise_trader.py`
- `tests/bots/test_bot_pool.py`
- `tests/bots/test_runner.py`

**.gitignore:** add `agentpit_bots/creds.json`

---

## Task 1: Schema migration — upstream token IDs and is_bot flag

**Files:**
- Modify: `agentpit/db/table_create.py`
- Modify: `agentpit/datastructures/market.py`
- Modify: `agentpit/datastructures/create_market_request.py`
- Modify: `agentpit/datastructures/user.py`
- Modify: `agentpit/db/table_write.py`
- Modify: `agentpit/db/table_read.py`
- Test: `tests/api/test_polymarket_token_ids.py`

- [ ] **Step 1: Write the failing test** — `tests/api/test_polymarket_token_ids.py`

```python
"""Schema migration: new columns are present and round-trip via the DAL."""
import sqlite3

from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    TableCreate.create_all_tables(conn)
    return conn


def test_markets_table_has_upstream_token_id_columns():
    conn = _make_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}
    assert "POLYMARKET_YES_TOKEN_ID" in cols
    assert "POLYMARKET_NO_TOKEN_ID" in cols


def test_users_table_has_is_bot_column():
    conn = _make_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "IS_BOT" in cols
    # Default 0
    conn.execute(
        "INSERT INTO users (USER_ID, EMAIL, PASSWORD_HASH, ETH_ADDRESS, "
        "ETH_PRIVATE_KEY, API_KEY, CREATED_AT) VALUES "
        "('u1','a@b','x','0xabc','0xkey','ak',1)"
    )
    row = conn.execute("SELECT IS_BOT FROM users WHERE USER_ID='u1'").fetchone()
    assert row[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -s tests/api/test_polymarket_token_ids.py::test_markets_table_has_upstream_token_id_columns -v`
Expected: FAIL (`POLYMARKET_YES_TOKEN_ID` not in cols).

- [ ] **Step 3: Add the schema columns** — edit `agentpit/db/table_create.py`

In `create_markets_table`, after the existing additive migrations block (around line 158, after the `ICON_URL` check), add:

```python
        if "POLYMARKET_YES_TOKEN_ID" not in cols:
            db.execute(
                "ALTER TABLE markets ADD COLUMN POLYMARKET_YES_TOKEN_ID TEXT"
            )
        if "POLYMARKET_NO_TOKEN_ID" not in cols:
            db.execute(
                "ALTER TABLE markets ADD COLUMN POLYMARKET_NO_TOKEN_ID TEXT"
            )
```

Also add the new columns to the canonical `CREATE TABLE` SQL inside `create_markets_table` (so fresh DBs get them too) just after `ICON_URL TEXT,`:

```python
                POLYMARKET_YES_TOKEN_ID TEXT,
                POLYMARKET_NO_TOKEN_ID TEXT,
```

In `_migrate_users_table`, add to the `additions` list:

```python
            ("IS_BOT", "INTEGER NOT NULL DEFAULT 0"),
```

Wait — SQLite cannot `ADD COLUMN ... NOT NULL` without a constant default. `DEFAULT 0` qualifies, so this is OK. Add it.

Also add `IS_BOT INTEGER NOT NULL DEFAULT 0` to the canonical `create_users_table` `CREATE TABLE` block (just before the closing parenthesis):

```python
                IS_BOT INTEGER NOT NULL DEFAULT 0
```

(Comma after `CREATED_AT INTEGER NOT NULL` — make sure trailing comma rules are respected.)

- [ ] **Step 4: Run schema tests to verify they pass**

Run: `pytest -s tests/api/test_polymarket_token_ids.py -v`
Expected: PASS on both column-existence tests.

- [ ] **Step 5: Extend `Market` and `CreateMarketRequest` datastructures**

Edit `agentpit/datastructures/market.py` — add two optional fields next to `polymarket_id`:

```python
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None
```

Edit `agentpit/datastructures/create_market_request.py` — add the same two optional fields.

Edit `agentpit/datastructures/user.py` — add `is_bot: bool = False`.

- [ ] **Step 6: Update DAL write/read**

In `agentpit/db/table_write.py`:

- Find the `create_market` INSERT statement. Add `POLYMARKET_YES_TOKEN_ID, POLYMARKET_NO_TOKEN_ID` to the column list and bind `req.polymarket_yes_token_id, req.polymarket_no_token_id` to the params.
- Add a new method:

```python
    @staticmethod
    def mark_user_as_bot(db: sqlite3.Connection, api_key: str) -> bool:
        cur = db.execute(
            "UPDATE users SET IS_BOT = 1 WHERE API_KEY = ?", (api_key,)
        )
        return cur.rowcount > 0
```

In `agentpit/db/table_read.py`:

- Find every place that builds a `Market(...)` from a row and pass `polymarket_yes_token_id=row["POLYMARKET_YES_TOKEN_ID"], polymarket_no_token_id=row["POLYMARKET_NO_TOKEN_ID"]`. Be sure to update each `Market(...)` constructor call (search file for `Market(` to find them).
- Find every place that builds a `User(...)` from a row and pass `is_bot=bool(row["IS_BOT"])`. Search file for `User(` to find them.

- [ ] **Step 7: Write a round-trip test for the new market fields** — append to `tests/api/test_polymarket_token_ids.py`:

```python
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState


def test_create_market_round_trips_upstream_token_ids():
    conn = _make_db()
    req = CreateMarketRequest(
        question="Q",
        description="D",
        polymarket_id=42,
        polymarket_condition_id="0xabc",
        polymarket_yes_token_id="111",
        polymarket_no_token_id="222",
        erc1155_tokens=[("0xaaa", "Yes"), ("0xbbb", "No")],
        slug="q",
        start_date=0,
        end_date=1,
        state=MarketState.ACTIVE,
        condition_id=ConditionId("0xabc"),
        outcome_label=None,
        icon_url=None,
    )
    market = TableWrite.create_market(conn, req, True)
    fetched = TableRead.read_market(conn, market.market_id)
    assert fetched.polymarket_yes_token_id == "111"
    assert fetched.polymarket_no_token_id == "222"
```

- [ ] **Step 8: Run all schema tests**

Run: `pytest -s tests/api/test_polymarket_token_ids.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_write.py agentpit/db/table_read.py \
        agentpit/datastructures/market.py agentpit/datastructures/create_market_request.py \
        agentpit/datastructures/user.py tests/api/test_polymarket_token_ids.py
git commit -m "schema: persist upstream Polymarket token IDs and is_bot user flag"
```

---

## Task 2: Capture upstream Polymarket token IDs during sync

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py`
- Test: `tests/api/test_polymarket_token_ids.py` (append)

The sync replaces upstream `conditionId`/`tokenIds` with locally-derived ones in `create_polygon_market_if_does_not_exist` ([polymarket_sync.py:515-553](../../../agentpit/polymarket/polymarket_sync.py#L515-L553)). We need to grab the upstream tokens *before* the overwrite and stash them on the request.

- [ ] **Step 1: Write the failing test** — append to `tests/api/test_polymarket_token_ids.py`:

```python
from agentpit.polymarket.polymarket_sync import build_create_market_request_from_json


def test_build_request_extracts_upstream_token_ids():
    pm_market = {
        "question": "Q",
        "description": "D",
        "id": 99,
        "conditionId": "0xcond",
        "slug": "q",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-12-31T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": "777", "outcome": "Yes"},
            {"token_id": "888", "outcome": "No"},
        ],
    }
    req = build_create_market_request_from_json(pm_market)
    assert req.polymarket_yes_token_id == "777"
    assert req.polymarket_no_token_id == "888"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/api/test_polymarket_token_ids.py::test_build_request_extracts_upstream_token_ids -v`
Expected: FAIL (`polymarket_yes_token_id` is None).

- [ ] **Step 3: Add an extractor + thread fields through `build_create_market_request_from_json`**

Edit `agentpit/polymarket/polymarket_sync.py`. Above `build_create_market_request_from_json`, add:

```python
def _extract_yes_no_token_ids(pm_market: dict) -> tuple[str | None, str | None]:
    """Return (yes_token_id, no_token_id) from a Polymarket market's tokens list.

    Polymarket binary markets list two tokens — one with outcome "Yes" and one
    with outcome "No". We match case-insensitively. Returns (None, None) if
    either side is missing or the market isn't binary.
    """
    tokens = pm_market.get("tokens") or []
    yes_id: str | None = None
    no_id: str | None = None
    for t in tokens:
        if not isinstance(t, dict):
            continue
        tid = t.get("token_id") or t.get("tokenId")
        outcome = (t.get("outcome") or t.get("label") or "").strip().lower()
        if tid is None:
            continue
        if outcome == "yes":
            yes_id = str(tid)
        elif outcome == "no":
            no_id = str(tid)
    return yes_id, no_id
```

Inside `build_create_market_request_from_json`, just before building `request = CreateMarketRequest(...)`, add:

```python
    yes_tok, no_tok = _extract_yes_no_token_ids(pm_market)
```

Add the two fields to the `CreateMarketRequest(...)` constructor:

```python
        polymarket_yes_token_id=yes_tok,
        polymarket_no_token_id=no_tok,
```

- [ ] **Step 4: Run sync test**

Run: `pytest -s tests/api/test_polymarket_token_ids.py::test_build_request_extracts_upstream_token_ids -v`
Expected: PASS.

- [ ] **Step 5: Make sure existing sync tests still pass**

Run: `pytest -s tests/polymarket/ -v` (live tests skipped without `--integration` marker — that's fine; unit tests should pass).

Run: `pytest -s tests/api/test_polymarket_token_ids.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/api/test_polymarket_token_ids.py
git commit -m "polymarket_sync: capture upstream YES/NO token IDs before local CTF overwrite"
```

---

## Task 3: `POST /admin/mark_bot` endpoint

**Files:**
- Create: `agentpit/api/routes/admin.py`
- Modify: `agentpit/api/app.py`
- Modify: `agentpit/config.py`
- Test: `tests/api/test_admin.py`

- [ ] **Step 1: Write the failing test** — `tests/api/test_admin.py`

```python
"""Admin endpoints — guarded by an X-Admin-Token header."""
import os

from fastapi.testclient import TestClient

from agentpit.api.main import app

# AGENTPIT_ADMIN_TOKEN is read at app startup by Settings; tests rely on
# the default ("dev-admin-token") so we don't need to mutate env here.
ADMIN_TOKEN = "dev-admin-token"


def _register(client: TestClient, email: str) -> dict:
    return client.post(
        "/register",
        json={"email": email, "password": "hunter22hunter22"},
    ).json()


def test_mark_bot_requires_admin_token():
    with TestClient(app) as client:
        user = _register(client, "mark1@example.com")
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": user["user"]["eth_address"]},
        )
        assert resp.status_code == 401


def test_mark_bot_flips_is_bot_flag():
    with TestClient(app) as client:
        user = _register(client, "mark2@example.com")
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": user["user"]["eth_address"]},
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"eth_address": user["user"]["eth_address"], "is_bot": True}


def test_mark_bot_unknown_address_404():
    with TestClient(app) as client:
        resp = client.post(
            "/admin/mark_bot",
            json={"eth_address": "0x0000000000000000000000000000000000000000"},
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/api/test_admin.py -v`
Expected: FAIL (route doesn't exist, 404 on all three).

- [ ] **Step 3: Add admin token to settings**

Edit `agentpit/config.py`. Add to the `Settings` class:

```python
    admin_token: str = Field(
        default="dev-admin-token",
        description="Shared secret for /admin/* endpoints (set via AGENTPIT_ADMIN_TOKEN)",
    )
```

- [ ] **Step 4: Add the `mark_user_as_bot_by_eth_address` DAL method**

Edit `agentpit/db/table_write.py` — add:

```python
    @staticmethod
    def mark_user_as_bot_by_eth_address(
        db: sqlite3.Connection, eth_address: str
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET IS_BOT = 1 WHERE LOWER(ETH_ADDRESS) = LOWER(?)",
            (eth_address,),
        )
        return cur.rowcount > 0
```

- [ ] **Step 5: Create the admin router** — `agentpit/api/routes/admin.py`

```python
"""Admin-only routes. Guarded by an X-Admin-Token header matching
``Settings.admin_token``.

These endpoints exist for operational bot management (flagging bot users
out of public leaderboards). They are not user-facing.
"""
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from agentpit.api.deps import SessionDep, SettingsDep
from agentpit.db.table_write import TableWrite

router = APIRouter(tags=["admin"], prefix="/admin")


class MarkBotRequest(BaseModel):
    eth_address: str


class MarkBotResponse(BaseModel):
    eth_address: str
    is_bot: bool


def _check_admin(provided: str | None, expected: str) -> None:
    if provided is None or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin token missing or invalid",
        )


@router.post("/mark_bot", response_model=MarkBotResponse)
def mark_bot(
    payload: MarkBotRequest,
    settings: SettingsDep,
    db: SessionDep,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> MarkBotResponse:
    _check_admin(x_admin_token, settings.admin_token)
    with db.write() as conn:
        updated = TableWrite.mark_user_as_bot_by_eth_address(
            conn, payload.eth_address
        )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no user with eth_address {payload.eth_address}",
        )
    return MarkBotResponse(eth_address=payload.eth_address, is_bot=True)
```

- [ ] **Step 6: Register the admin router in the app factory**

Edit `agentpit/api/app.py`. Locate the section that includes routers (`app.include_router(...)` calls). Add:

```python
    from agentpit.api.routes import admin as admin_routes
    app.include_router(admin_routes.router)
```

If the file already imports routes at the top, add the import alongside the others and the `include_router` call where the others are.

- [ ] **Step 7: Run admin tests**

Run: `pytest -s tests/api/test_admin.py -v`
Expected: all 3 PASS.

- [ ] **Step 8: Run the broader suite to check no regressions**

Run: `pytest -s tests/api -v`
Expected: PASS (allowing for any pre-existing failures unrelated to this change — note them but don't fix in this task).

- [ ] **Step 9: Commit**

```bash
git add agentpit/api/routes/admin.py agentpit/api/app.py agentpit/config.py \
        agentpit/db/table_write.py tests/api/test_admin.py
git commit -m "api: add POST /admin/mark_bot for flagging bot user accounts"
```

---

## Task 4: `GET /orders/mine` — list current user's live orders

**Files:**
- Modify: `agentpit/services/order_service.py`
- Modify: `agentpit/api/routes/orders.py`
- Modify: `agentpit/db/table_read.py`
- Test: `tests/api/test_orders_mine.py`

- [ ] **Step 1: Write the failing test** — `tests/api/test_orders_mine.py`

```python
"""GET /orders/mine returns the caller's live orders for reconciliation."""
from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_orders_mine_returns_empty_for_new_user():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "mine1@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.get("/orders/mine", headers=_hdr(body["access_token"]))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"orders": []}


def test_orders_mine_requires_auth():
    with TestClient(app) as client:
        resp = client.get("/orders/mine")
        assert resp.status_code == 401
```

(A test for actually-placed orders is added later as part of the bot integration test — placing orders requires a real ACTIVE market plus on-chain settlement and is more naturally tested in the bot integration test.)

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/api/test_orders_mine.py -v`
Expected: FAIL on the first test (404 — route doesn't exist).

- [ ] **Step 3: Add the DAL read**

Note: the `orders` table doesn't store `market_id` directly — it stores `TOKEN_ID`. We return `TOKEN_ID` alongside the other fields and let the bot client resolve `market_id` from its in-memory market list (it already has one for the anchor MM).

Edit `agentpit/db/table_read.py`. Add to the `TableRead` class:

```python
    @staticmethod
    def list_live_orders_for_api_key(
        db: sqlite3.Connection, api_key: str
    ) -> list[dict]:
        db.row_factory = sqlite3.Row
        cur = db.execute(
            """
            SELECT ORDER_ID, TOKEN_ID, SIDE, PRICE, REMAINING_AMOUNT,
                   MAKER, CREATED_AT, STATUS, ORDER_TYPE, EXPIRATION
            FROM orders
            WHERE API_KEY = ? AND STATUS = 'live'
            ORDER BY CREATED_AT DESC
            """,
            (api_key,),
        )
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 4: Add `list_live_orders` to `OrderService`**

Edit `agentpit/services/order_service.py`. Add a public method on `OrderService`:

```python
    def list_live_orders(self, user: User) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return TableRead.list_live_orders_for_api_key(conn, user.api_key)
```

- [ ] **Step 5: Add the route**

Edit `agentpit/api/routes/orders.py`. Add:

```python
@router.get("/orders/mine")
def list_my_orders(
    user: CurrentUserDep,
    service: OrderServiceDep,
) -> dict:
    return {"orders": service.list_live_orders(user)}
```

- [ ] **Step 6: Run orders/mine tests**

Run: `pytest -s tests/api/test_orders_mine.py -v`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add agentpit/services/order_service.py agentpit/api/routes/orders.py \
        agentpit/db/table_read.py tests/api/test_orders_mine.py
git commit -m "api: add GET /orders/mine for self-served order reconciliation"
```

---

## Task 5: Bot package skeleton + config

**Files:**
- Create: `agentpit_bots/__init__.py`
- Create: `agentpit_bots/config.py`
- Create: `tests/bots/__init__.py`
- Create: `tests/bots/conftest.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create empty package init** — `agentpit_bots/__init__.py`

```python
"""agentpit_bots — external liquidity bot service.

Runs as: ``python -m agentpit_bots.runner --base http://localhost:8000``

See ``docs/superpowers/specs/2026-05-18-liquidity-bots-design.md``.
"""
```

- [ ] **Step 2: Create config module** — `agentpit_bots/config.py`

```python
"""Bot service configuration. Defaults tuned for the v1 dead-book problem.

All knobs live here so operators can tune by editing one file. None of
these are exposed via env vars yet — keep it simple for v1.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotConfig:
    # --- cadence ---------------------------------------------------------
    tick_interval_sec: int = 30
    noise_tick_base_sec: int = 60
    noise_tick_jitter_sec: int = 20

    # --- pool sizing -----------------------------------------------------
    noise_pool_size: int = 3
    anchor_pool_size: int = 1   # one anchor MM per market is enough

    # --- anchor MM strategy ---------------------------------------------
    mm_half_spread_usd: float = 0.005       # $0.005 → ¢1 spread total
    mm_quote_size_shares: int = 100         # display shares; multiplied by 10^6 raw
    mm_rebalance_every_ticks: int = 10
    mm_rebalance_floor_shares: int = 200

    # --- noise strategy --------------------------------------------------
    noise_min_size_shares: int = 5
    noise_max_size_shares: int = 50
    noise_aggressive_prob: float = 0.3

    # --- oracle ----------------------------------------------------------
    oracle_stale_after_sec: int = 300

    # --- service ---------------------------------------------------------
    base_url: str = "http://localhost:8000"
    polymarket_clob_host: str = "https://clob.polymarket.com"
    admin_token: str = "dev-admin-token"
    creds_path: str = "agentpit_bots/creds.json"

    # --- per-market on/off ----------------------------------------------
    disabled_market_ids: frozenset[int] = field(default_factory=frozenset)

    # --- starting capital ----------------------------------------------
    # The faucet drip at /register sets initial USDC. We don't top up.
    inventory_split_shares: int = 500


DEFAULT = BotConfig()

SHARES_SCALE = 1_000_000   # raw outcome-token units per display share
```

- [ ] **Step 3: Add test init and shared fixtures** — `tests/bots/__init__.py` (empty), and `tests/bots/conftest.py`:

```python
"""Shared fixtures for bot unit tests.

Bot unit tests are pure — no DB, no network. They use the fakes here.
The integration test in tests/bots/test_runner.py is the only one that
spins up FastAPI/Anvil.
"""
import pytest


@pytest.fixture
def bot_config():
    from agentpit_bots.config import BotConfig
    return BotConfig(tick_interval_sec=1, noise_tick_base_sec=1)
```

- [ ] **Step 4: Update .gitignore**

Append to `.gitignore`:

```
agentpit_bots/creds.json
```

- [ ] **Step 5: Smoke test the import path**

```bash
python -c "from agentpit_bots.config import BotConfig, DEFAULT, SHARES_SCALE; print(DEFAULT.tick_interval_sec)"
```

Expected output: `30`.

- [ ] **Step 6: Commit**

```bash
git add agentpit_bots/__init__.py agentpit_bots/config.py \
        tests/bots/__init__.py tests/bots/conftest.py .gitignore
git commit -m "bots: package skeleton + config defaults"
```

---

## Task 6: `reconcile()` — pure diff between live and desired orders

**Files:**
- Create: `agentpit_bots/reconcile.py`
- Test: `tests/bots/test_reconcile.py`

`reconcile` is the only nontrivial piece of pure logic in the bot. Get it right with TDD.

- [ ] **Step 1: Write the failing test** — `tests/bots/test_reconcile.py`

```python
"""reconcile(live, desired) → (cancels, creates)

Two orders are considered equivalent when same (side, token_id, price_int, size).
Anything live that isn't matched gets cancelled. Anything desired not matched
gets created. The size match is exact — partial fills aren't treated as a match.
"""
from agentpit_bots.reconcile import DesiredOrder, LiveOrder, reconcile


def _live(order_id, side, token_id, price_int, size):
    return LiveOrder(
        order_id=order_id, side=side, token_id=token_id,
        price_int=price_int, remaining_amount=size,
    )


def _desired(side, token_id, price_int, size):
    return DesiredOrder(
        side=side, token_id=token_id, price_int=price_int, size=size,
    )


def test_empty_in_empty_out():
    cancels, creates = reconcile([], [])
    assert cancels == []
    assert creates == []


def test_all_desired_when_none_live():
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile([], desired)
    assert cancels == []
    assert creates == desired


def test_all_cancelled_when_none_desired():
    live = [_live("o1", "BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, [])
    assert cancels == ["o1"]
    assert creates == []


def test_exact_match_no_action():
    live = [_live("o1", "BUY", "t1", 500000, 100)]
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == []
    assert creates == []


def test_price_changed_cancels_and_recreates():
    live = [_live("o1", "BUY", "t1", 490000, 100)]
    desired = [_desired("BUY", "t1", 510000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == ["o1"]
    assert creates == desired


def test_partial_fill_counts_as_mismatch_and_recreates():
    live = [_live("o1", "BUY", "t1", 500000, 60)]   # was 100, 40 filled
    desired = [_desired("BUY", "t1", 500000, 100)]
    cancels, creates = reconcile(live, desired)
    assert cancels == ["o1"]
    assert creates == desired


def test_multi_outcome_independent():
    live = [
        _live("o1", "BUY",  "yes_tok", 500000, 100),   # keep
        _live("o2", "SELL", "yes_tok", 600000, 100),   # cancel (not desired)
        _live("o3", "BUY",  "no_tok",  400000, 100),   # keep
    ]
    desired = [
        _desired("BUY",  "yes_tok", 500000, 100),
        _desired("BUY",  "no_tok",  400000, 100),
        _desired("SELL", "yes_tok", 510000, 100),      # new — wasn't live
    ]
    cancels, creates = reconcile(live, desired)
    assert set(cancels) == {"o2"}
    assert creates == [_desired("SELL", "yes_tok", 510000, 100)]
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_reconcile.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `reconcile.py`**

`agentpit_bots/reconcile.py`:

```python
"""Diff a bot's currently live orders against the strategy's desired set.

Pure function — no IO. The caller turns the returned cancels and creates
into REST calls.
"""
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LiveOrder:
    order_id: str
    side: str            # "BUY" | "SELL"
    token_id: str
    price_int: int       # price scaled by 10^6
    remaining_amount: int


@dataclass(frozen=True)
class DesiredOrder:
    side: str
    token_id: str
    price_int: int
    size: int


def _key(side: str, token_id: str, price_int: int, size: int) -> tuple:
    return (side, token_id, price_int, size)


def reconcile(
    live: Iterable[LiveOrder],
    desired: Iterable[DesiredOrder],
) -> tuple[list[str], list[DesiredOrder]]:
    """Return ``(order_ids_to_cancel, desired_orders_to_create)``.

    An order is "matched" when its (side, token_id, price_int, size) tuple
    is shared between live and desired. Unmatched live → cancel.
    Unmatched desired → create.
    """
    live_list = list(live)
    desired_list = list(desired)
    desired_keys = {
        _key(d.side, d.token_id, d.price_int, d.size) for d in desired_list
    }
    live_keys = {
        _key(l.side, l.token_id, l.price_int, l.remaining_amount)
        for l in live_list
    }
    cancels = [
        l.order_id
        for l in live_list
        if _key(l.side, l.token_id, l.price_int, l.remaining_amount) not in desired_keys
    ]
    creates = [
        d for d in desired_list
        if _key(d.side, d.token_id, d.price_int, d.size) not in live_keys
    ]
    return cancels, creates
```

- [ ] **Step 4: Run reconcile tests**

Run: `pytest -s tests/bots/test_reconcile.py -v`
Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/reconcile.py tests/bots/test_reconcile.py
git commit -m "bots: reconcile() — pure diff between live and desired orders"
```

---

## Task 7: `PriceOracle` — batched + cached Polymarket midpoint fetcher

**Files:**
- Create: `agentpit_bots/price_oracle.py`
- Test: `tests/bots/test_price_oracle.py`

`py_clob_client.ClobClient.get_midpoints(BookParams[])` returns `{token_id: midpoint}`. We wrap it with caching + graceful staleness.

- [ ] **Step 1: Write the failing test** — `tests/bots/test_price_oracle.py`

```python
"""PriceOracle: batched + cached + tolerant of upstream failure."""
import time

import pytest

from agentpit_bots.price_oracle import PriceOracle, OracleSnapshot


class FakeClob:
    """Stand-in for py_clob_client.ClobClient."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.next_response: dict[str, float] = {}
        self.raise_next: bool = False

    def get_midpoints(self, params):
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError("polymarket down")
        token_ids = [p.token_id for p in params]
        self.calls.append(list(token_ids))
        return {tid: self.next_response.get(tid) for tid in token_ids}


@pytest.fixture
def fake_clob():
    return FakeClob()


def test_refresh_batches_into_one_call(fake_clob):
    fake_clob.next_response = {"t1": 0.42, "t2": 0.71}
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh(["t1", "t2"])
    assert snap.midpoint("t1") == 0.42
    assert snap.midpoint("t2") == 0.71
    assert fake_clob.calls == [["t1", "t2"]]


def test_midpoint_uses_cache_until_explicit_refresh(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh(["t1"])
    assert snap.midpoint("t1") == 0.5
    # change upstream — without refresh, snap still reads 0.5
    fake_clob.next_response = {"t1": 0.9}
    assert snap.midpoint("t1") == 0.5


def test_refresh_failure_keeps_previous_snapshot(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob)
    oracle.refresh(["t1"])
    fake_clob.raise_next = True
    snap = oracle.refresh(["t1"])   # second call raises; oracle swallows
    assert snap.midpoint("t1") == 0.5
    assert snap.is_stale("t1", stale_after_sec=10**9) is False  # within window


def test_is_stale_when_older_than_threshold(fake_clob):
    fake_clob.next_response = {"t1": 0.5}
    oracle = PriceOracle(clob=fake_clob, now_fn=lambda: 1000)
    snap = oracle.refresh(["t1"])
    # snap was fetched at t=1000; later we ask with stale_after_sec=10 at t=1100
    assert snap.is_stale("t1", stale_after_sec=10, now=1100) is True
    assert snap.is_stale("t1", stale_after_sec=200, now=1100) is False


def test_midpoint_unknown_token_returns_none(fake_clob):
    oracle = PriceOracle(clob=fake_clob)
    snap = oracle.refresh([])
    assert snap.midpoint("nope") is None
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_price_oracle.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `price_oracle.py`**

`agentpit_bots/price_oracle.py`:

```python
"""Polymarket midpoint oracle — batched, cached, graceful on failure.

Wraps ``py_clob_client.ClobClient``. Stores the most recent successful
fetch per token in an in-memory snapshot; on upstream failure, returns
the stale snapshot rather than raising — callers check ``is_stale`` to
decide whether to act.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

log = logging.getLogger(__name__)


class _ClobLike(Protocol):
    def get_midpoints(self, params): ...   # noqa: D401, ANN001


@dataclass
class OracleSnapshot:
    """An immutable view of the latest cached midpoints."""

    data: dict[str, float] = field(default_factory=dict)
    fetched_at: dict[str, float] = field(default_factory=dict)

    def midpoint(self, token_id: str) -> float | None:
        return self.data.get(token_id)

    def is_stale(
        self, token_id: str, *, stale_after_sec: int, now: float | None = None
    ) -> bool:
        ts = self.fetched_at.get(token_id)
        if ts is None:
            return True
        current = now if now is not None else time.time()
        return (current - ts) > stale_after_sec


class PriceOracle:
    def __init__(
        self,
        clob: _ClobLike,
        *,
        now_fn: Callable[[], float] = time.time,
    ):
        self._clob = clob
        self._now = now_fn
        self._snap = OracleSnapshot()

    def refresh(self, token_ids: Iterable[str]) -> OracleSnapshot:
        """Fetch midpoints for ``token_ids`` in one batched call.

        On HTTP/connection failure: log + return the current snapshot
        unchanged. Callers check ``OracleSnapshot.is_stale(...)`` to decide
        whether to act on values from the snapshot.
        """
        # Import locally so unit tests don't need py_clob_client installed.
        from py_clob_client.clob_types import BookParams

        token_id_list = list(token_ids)
        if not token_id_list:
            return self._snap
        params = [BookParams(token_id=tid) for tid in token_id_list]
        try:
            response = self._clob.get_midpoints(params)
        except Exception:
            log.warning(
                "oracle_fetch_failed tokens=%d serving_stale=%d",
                len(token_id_list), len(self._snap.data),
            )
            return self._snap
        now = self._now()
        new_data = dict(self._snap.data)
        new_fetched = dict(self._snap.fetched_at)
        for tid in token_id_list:
            value = response.get(tid)
            if value is None:
                continue
            new_data[tid] = float(value)
            new_fetched[tid] = now
        self._snap = OracleSnapshot(data=new_data, fetched_at=new_fetched)
        return self._snap

    @property
    def snapshot(self) -> OracleSnapshot:
        return self._snap
```

- [ ] **Step 4: Run oracle tests**

Run: `pytest -s tests/bots/test_price_oracle.py -v`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/price_oracle.py tests/bots/test_price_oracle.py
git commit -m "bots: PriceOracle with batched fetch and graceful staleness"
```

---

## Task 8: `AgentpitClient` — REST wrapper

**Files:**
- Create: `agentpit_bots/client.py`
- Test: `tests/bots/test_client.py`

- [ ] **Step 1: Write the failing test** — `tests/bots/test_client.py`

```python
"""AgentpitClient — REST wrapper.

We don't use a real network — use a fake `requests`-like session that
records calls.
"""
import json
from dataclasses import dataclass

import pytest

from agentpit_bots.client import AgentpitClient


class FakeResponse:
    def __init__(self, status_code: int, body: dict | list | None = None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict]] = []
        self.next_response: FakeResponse = FakeResponse(200)

    def request(self, method, url, *, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, dict(headers or {})))
        return self.next_response


@pytest.fixture
def session():
    return FakeSession()


def test_register_persists_and_returns_creds(session):
    session.next_response = FakeResponse(200, {
        "access_token": "tok-abc",
        "user": {"eth_address": "0xDEAD"},
    })
    c = AgentpitClient(base_url="http://x", session=session)
    creds = c.register(email="bot@x", password="hunter22hunter22")
    assert creds.token == "tok-abc"
    assert creds.eth_address == "0xDEAD"
    method, url, body, _ = session.calls[0]
    assert method == "POST"
    assert url == "http://x/register"
    assert body == {"email": "bot@x", "password": "hunter22hunter22"}


def test_place_order_includes_bearer_token(session):
    session.next_response = FakeResponse(200, {
        "success": True, "orderID": "0x1", "status": "live",
        "filledSize": "0", "remainingSize": "100",
    })
    c = AgentpitClient(base_url="http://x", session=session)
    c.place_order(
        token="tok-abc",
        market_id=1, outcome="Yes", side="BUY",
        price="0.5", size=100_000_000,
    )
    method, url, body, headers = session.calls[0]
    assert method == "POST"
    assert url == "http://x/orders"
    assert body == {
        "market_id": 1, "outcome": "Yes", "side": "BUY",
        "price": "0.5", "size": 100_000_000, "order_type": "GTC",
        "expiration": 0,
    }
    assert headers["Authorization"] == "Bearer tok-abc"


def test_list_mine(session):
    session.next_response = FakeResponse(200, {"orders": [{"ORDER_ID": "o1"}]})
    c = AgentpitClient(base_url="http://x", session=session)
    orders = c.list_my_orders(token="tok-abc")
    assert orders == [{"ORDER_ID": "o1"}]


def test_cancel_order(session):
    session.next_response = FakeResponse(200, {"order_id": "o1", "status": "cancelled"})
    c = AgentpitClient(base_url="http://x", session=session)
    c.cancel_order(token="tok-abc", order_id="o1")
    method, url, _, _ = session.calls[0]
    assert method == "DELETE"
    assert url == "http://x/orders/o1"


def test_mark_bot_uses_admin_header(session):
    session.next_response = FakeResponse(200, {"eth_address": "0xa", "is_bot": True})
    c = AgentpitClient(base_url="http://x", session=session, admin_token="secret")
    c.mark_bot(eth_address="0xa")
    method, url, body, headers = session.calls[0]
    assert method == "POST"
    assert url == "http://x/admin/mark_bot"
    assert body == {"eth_address": "0xa"}
    assert headers["X-Admin-Token"] == "secret"


def test_split_position(session):
    session.next_response = FakeResponse(200, {})
    c = AgentpitClient(base_url="http://x", session=session)
    c.split_position(token="tok-abc", market_id=5, amount=500)
    method, url, body, _ = session.calls[0]
    assert method == "POST"
    assert url == "http://x/markets/5/split_position"
    assert body == {"amount": 500}


def test_merge_positions(session):
    session.next_response = FakeResponse(200, {})
    c = AgentpitClient(base_url="http://x", session=session)
    c.merge_positions(token="tok-abc", market_id=5, amount=200)
    method, url, body, _ = session.calls[0]
    assert url == "http://x/markets/5/merge_positions"
    assert body == {"amount": 200}


def test_get_markets(session):
    session.next_response = FakeResponse(200, [{"market_id": 1}])
    c = AgentpitClient(base_url="http://x", session=session)
    out = c.get_markets()
    assert out == [{"market_id": 1}]
    method, url, _, _ = session.calls[0]
    assert method == "GET"
    assert url == "http://x/markets"


def test_get_portfolio(session):
    session.next_response = FakeResponse(200, {"usdc_balance": 1000, "positions": []})
    c = AgentpitClient(base_url="http://x", session=session)
    out = c.get_portfolio(token="tok-abc")
    assert out["usdc_balance"] == 1000
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_client.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `client.py`**

`agentpit_bots/client.py`:

```python
"""Thin REST wrapper over the AgentPit API.

The runner instantiates one of these and shares it across bots — auth
tokens are per-bot and passed per-call rather than stored on the client.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _SessionLike(Protocol):
    def request(self, method, url, *, json=None, headers=None, timeout=None): ...   # noqa: ANN001


@dataclass(frozen=True)
class BotCredentials:
    token: str
    eth_address: str


class AgentpitClient:
    def __init__(
        self,
        *,
        base_url: str,
        session: _SessionLike,
        admin_token: str = "",
        timeout: float = 15.0,
    ):
        self._base = base_url.rstrip("/")
        self._session = session
        self._admin_token = admin_token
        self._timeout = timeout

    # --- auth -----------------------------------------------------------

    def register(self, *, email: str, password: str) -> BotCredentials:
        body = self._post("/register", body={"email": email, "password": password})
        return BotCredentials(
            token=body["access_token"],
            eth_address=body["user"]["eth_address"],
        )

    # --- orders ---------------------------------------------------------

    def place_order(
        self, *, token: str, market_id: int, outcome: str, side: str,
        price: str, size: int,
    ) -> dict[str, Any]:
        return self._post(
            "/orders",
            body={
                "market_id": market_id, "outcome": outcome, "side": side,
                "price": price, "size": size, "order_type": "GTC",
                "expiration": 0,
            },
            token=token,
        )

    def list_my_orders(self, *, token: str) -> list[dict[str, Any]]:
        return self._get("/orders/mine", token=token)["orders"]

    def cancel_order(self, *, token: str, order_id: str) -> dict[str, Any]:
        return self._delete(f"/orders/{order_id}", token=token)

    def get_orderbook(self, *, market_id: int, outcome: str) -> dict[str, Any]:
        return self._get(f"/orderbook/{market_id}/{outcome}")

    # --- markets --------------------------------------------------------

    def get_markets(self) -> list[dict[str, Any]]:
        return self._get("/markets")

    def get_portfolio(self, *, token: str) -> dict[str, Any]:
        return self._get("/portfolio", token=token)

    def split_position(
        self, *, token: str, market_id: int, amount: int
    ) -> dict[str, Any]:
        return self._post(
            f"/markets/{market_id}/split_position",
            body={"amount": amount}, token=token,
        )

    def merge_positions(
        self, *, token: str, market_id: int, amount: int
    ) -> dict[str, Any]:
        return self._post(
            f"/markets/{market_id}/merge_positions",
            body={"amount": amount}, token=token,
        )

    # --- admin ----------------------------------------------------------

    def mark_bot(self, *, eth_address: str) -> dict[str, Any]:
        if not self._admin_token:
            raise RuntimeError("AgentpitClient: admin_token not configured")
        return self._post(
            "/admin/mark_bot",
            body={"eth_address": eth_address},
            extra_headers={"X-Admin-Token": self._admin_token},
        )

    # --- low-level ------------------------------------------------------

    def _post(self, path, *, body=None, token=None, extra_headers=None):
        return self._call("POST", path, body=body, token=token, extra_headers=extra_headers)

    def _get(self, path, *, token=None):
        return self._call("GET", path, token=token)

    def _delete(self, path, *, token=None):
        return self._call("DELETE", path, token=token)

    def _call(self, method, path, *, body=None, token=None, extra_headers=None):
        headers: dict[str, str] = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        resp = self._session.request(
            method, self._base + path,
            json=body, headers=headers, timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"{method} {path} → HTTP {resp.status_code}: {resp.text}"
            )
        return resp.json()
```

- [ ] **Step 4: Run client tests**

Run: `pytest -s tests/bots/test_client.py -v`
Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/client.py tests/bots/test_client.py
git commit -m "bots: AgentpitClient REST wrapper covering register/orders/markets/admin"
```

---

## Task 9: `AnchorMarketMaker` strategy

**Files:**
- Create: `agentpit_bots/strategies/__init__.py`
- Create: `agentpit_bots/strategies/base.py`
- Create: `agentpit_bots/strategies/anchor_mm.py`
- Test: `tests/bots/test_anchor_mm.py`

- [ ] **Step 1: Write the failing test** — `tests/bots/test_anchor_mm.py`

```python
"""AnchorMarketMaker.compute_desired_orders — pure function over (market, mid)."""
from agentpit_bots.config import BotConfig, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.anchor_mm import AnchorMarketMaker, MarketTokens


def _market(yes_tok="yes-local", no_tok="no-local") -> MarketTokens:
    return MarketTokens(market_id=1, yes_token_id=yes_tok, no_token_id=no_tok)


def test_two_sided_quotes_around_midpoint():
    cfg = BotConfig(mm_half_spread_usd=0.01, mm_quote_size_shares=100)
    strat = AnchorMarketMaker(cfg)
    desired = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.50)
    by_key = {(d.side, d.token_id): d for d in desired}
    assert by_key[("BUY", "yes-local")].price_int == 490_000
    assert by_key[("SELL", "yes-local")].price_int == 510_000
    assert by_key[("BUY", "no-local")].price_int == 490_000
    assert by_key[("SELL", "no-local")].price_int == 510_000
    for d in desired:
        assert d.size == 100 * SHARES_SCALE


def test_mid_clipped_within_bounds():
    cfg = BotConfig(mm_half_spread_usd=0.05)
    strat = AnchorMarketMaker(cfg)
    desired = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.005)
    # YES bid would land at 0.005 - 0.05 = -0.045 → clipped to 0.01
    yes_buy = next(d for d in desired if d.side == "BUY" and d.token_id == "yes-local")
    assert yes_buy.price_int == 10_000   # $0.01 scaled


def test_no_quotes_when_mid_is_none():
    cfg = BotConfig()
    strat = AnchorMarketMaker(cfg)
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_anchor_mm.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Strategy base** — `agentpit_bots/strategies/__init__.py` (empty) and `agentpit_bots/strategies/base.py`:

```python
"""Strategy abstract interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentpit_bots.reconcile import DesiredOrder


@dataclass(frozen=True)
class MarketTokens:
    """The minimal market info a strategy needs.

    The runner builds this from the `markets` table (local CTF token IDs)
    plus the `polymarket_yes_token_id` upstream IDs used by the oracle.
    """
    market_id: int
    yes_token_id: str       # local CTF id used in /orders
    no_token_id: str        # local CTF id used in /orders


class Strategy(ABC):
    @abstractmethod
    def compute_desired_orders(self, **kwargs) -> list[DesiredOrder]:
        ...
```

- [ ] **Step 4: Implement `anchor_mm.py`** — `agentpit_bots/strategies/anchor_mm.py`:

```python
"""Two-sided market maker anchored on Polymarket midpoint.

For each market the bot covers, quotes YES bid/ask around the upstream
mid and mirrors NO at (1 - mid) ± half_spread. Sizes and spread come
from BotConfig. Output is a list of DesiredOrder — pure function.
"""
from __future__ import annotations

from agentpit_bots.config import BotConfig, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.base import MarketTokens, Strategy

_MIN_PRICE = 0.01
_MAX_PRICE = 0.99
_PRICE_SCALE = 1_000_000   # USDC micro-units


def _clip(x: float) -> float:
    return max(_MIN_PRICE, min(_MAX_PRICE, x))


def _price_int(p: float) -> int:
    return int(round(p * _PRICE_SCALE))


class AnchorMarketMaker(Strategy):
    def __init__(self, cfg: BotConfig):
        self._cfg = cfg

    def compute_desired_orders(
        self, *, market: MarketTokens, poly_yes_mid: float | None
    ) -> list[DesiredOrder]:
        if poly_yes_mid is None:
            return []
        size = self._cfg.mm_quote_size_shares * SHARES_SCALE
        half = self._cfg.mm_half_spread_usd

        yes_bid = _clip(poly_yes_mid - half)
        yes_ask = _clip(poly_yes_mid + half)
        no_mid = 1.0 - poly_yes_mid
        no_bid = _clip(no_mid - half)
        no_ask = _clip(no_mid + half)

        return [
            DesiredOrder(side="BUY",  token_id=market.yes_token_id,
                         price_int=_price_int(yes_bid), size=size),
            DesiredOrder(side="SELL", token_id=market.yes_token_id,
                         price_int=_price_int(yes_ask), size=size),
            DesiredOrder(side="BUY",  token_id=market.no_token_id,
                         price_int=_price_int(no_bid), size=size),
            DesiredOrder(side="SELL", token_id=market.no_token_id,
                         price_int=_price_int(no_ask), size=size),
        ]
```

- [ ] **Step 5: Run anchor MM tests**

Run: `pytest -s tests/bots/test_anchor_mm.py -v`
Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit_bots/strategies/__init__.py agentpit_bots/strategies/base.py \
        agentpit_bots/strategies/anchor_mm.py tests/bots/test_anchor_mm.py
git commit -m "bots: AnchorMarketMaker strategy with symmetric quotes around Polymarket mid"
```

---

## Task 10: `NoiseTrader` strategy

**Files:**
- Create: `agentpit_bots/strategies/noise_trader.py`
- Test: `tests/bots/test_noise_trader.py`

- [ ] **Step 1: Write the failing test** — `tests/bots/test_noise_trader.py`

```python
"""NoiseTrader generates a single random order per tick within size/price bounds."""
import random

from agentpit_bots.config import BotConfig, SHARES_SCALE
from agentpit_bots.strategies.anchor_mm import _PRICE_SCALE
from agentpit_bots.strategies.noise_trader import NoiseTrader
from agentpit_bots.strategies.base import MarketTokens


def _market():
    return MarketTokens(market_id=7, yes_token_id="yest", no_token_id="not")


def test_returns_one_order_within_size_bounds():
    cfg = BotConfig(noise_min_size_shares=5, noise_max_size_shares=10)
    strat = NoiseTrader(cfg, rng=random.Random(42))
    orders = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.5)
    assert len(orders) == 1
    o = orders[0]
    assert 5 * SHARES_SCALE <= o.size <= 10 * SHARES_SCALE
    assert o.side in {"BUY", "SELL"}
    assert o.token_id in {"yest", "not"}


def test_no_orders_when_mid_unknown():
    cfg = BotConfig()
    strat = NoiseTrader(cfg, rng=random.Random(0))
    assert strat.compute_desired_orders(market=_market(), poly_yes_mid=None) == []


def test_aggressive_mode_crosses_inside():
    """When aggressive_prob=1.0 the order should be marketable.

    For a BUY YES: price >= mid + half_spread (lifts asks).
    For a SELL YES: price <= mid - half_spread (hits bids).
    The fake config has mm_half_spread_usd=0.01 so anchor band is [0.49, 0.51]
    at mid=0.5. An aggressive BUY YES should price >= 0.51.
    """
    cfg = BotConfig(noise_aggressive_prob=1.0, mm_half_spread_usd=0.01)
    strat = NoiseTrader(cfg, rng=random.Random(1))
    # Force enough draws to see a YES side; run 20 iterations and check the
    # invariant on each marketable YES BUY.
    for _ in range(20):
        orders = strat.compute_desired_orders(market=_market(), poly_yes_mid=0.5)
        if not orders:
            continue
        o = orders[0]
        if o.side == "BUY" and o.token_id == "yest":
            assert o.price_int >= int(0.51 * _PRICE_SCALE)
        elif o.side == "SELL" and o.token_id == "yest":
            assert o.price_int <= int(0.49 * _PRICE_SCALE)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_noise_trader.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `noise_trader.py`** — `agentpit_bots/strategies/noise_trader.py`:

```python
"""NoiseTrader: occasional random orders to keep the book ticking.

Per tick: 50/50 picks YES or NO outcome, 50/50 picks BUY or SELL side,
draws a random size from config bounds. With probability noise_aggressive_prob
the order is marketable (crosses the anchor band); otherwise it's a resting
order inside the band.
"""
from __future__ import annotations

import random

from agentpit_bots.config import BotConfig, SHARES_SCALE
from agentpit_bots.reconcile import DesiredOrder
from agentpit_bots.strategies.anchor_mm import _PRICE_SCALE, _clip
from agentpit_bots.strategies.base import MarketTokens, Strategy


class NoiseTrader(Strategy):
    def __init__(self, cfg: BotConfig, *, rng: random.Random | None = None):
        self._cfg = cfg
        self._rng = rng or random.Random()

    def compute_desired_orders(
        self, *, market: MarketTokens, poly_yes_mid: float | None
    ) -> list[DesiredOrder]:
        if poly_yes_mid is None:
            return []
        rng = self._rng
        cfg = self._cfg

        is_yes = rng.random() < 0.5
        side = "BUY" if rng.random() < 0.5 else "SELL"
        token_id = market.yes_token_id if is_yes else market.no_token_id
        size_shares = rng.randint(cfg.noise_min_size_shares, cfg.noise_max_size_shares)

        # Anchor band — mirrors AnchorMarketMaker.
        mid = poly_yes_mid if is_yes else 1.0 - poly_yes_mid
        half = cfg.mm_half_spread_usd
        aggressive = rng.random() < cfg.noise_aggressive_prob

        if side == "BUY":
            if aggressive:
                # Cross the ask — lift it.
                price = _clip(mid + half + 0.005)
            else:
                price = _clip(mid - half - 0.005)
        else:
            if aggressive:
                price = _clip(mid - half - 0.005)
            else:
                price = _clip(mid + half + 0.005)

        return [DesiredOrder(
            side=side, token_id=token_id,
            price_int=int(round(price * _PRICE_SCALE)),
            size=size_shares * SHARES_SCALE,
        )]
```

- [ ] **Step 4: Run noise trader tests**

Run: `pytest -s tests/bots/test_noise_trader.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/strategies/noise_trader.py tests/bots/test_noise_trader.py
git commit -m "bots: NoiseTrader strategy with aggressive/resting modes"
```

---

## Task 11: `BotPool` — register, fund, persist creds, split inventory

**Files:**
- Create: `agentpit_bots/bot_pool.py`
- Test: `tests/bots/test_bot_pool.py`

- [ ] **Step 1: Write the failing test** — `tests/bots/test_bot_pool.py`

```python
"""BotPool — bootstrap registers bots, persists creds, splits inventory."""
import json
import os
from pathlib import Path

import pytest

from agentpit_bots.bot_pool import Bot, BotPool, BotRole
from agentpit_bots.client import BotCredentials


class FakeClient:
    def __init__(self):
        self.registered: list[tuple[str, str]] = []
        self.marked: list[str] = []
        self.split: list[tuple[str, int, int]] = []
        self._next_eth = iter(["0xa1", "0xa2", "0xa3", "0xa4"])

    def register(self, *, email, password):
        self.registered.append((email, password))
        addr = next(self._next_eth)
        return BotCredentials(token=f"tok-{addr}", eth_address=addr)

    def mark_bot(self, *, eth_address):
        self.marked.append(eth_address)
        return {"eth_address": eth_address, "is_bot": True}

    def split_position(self, *, token, market_id, amount):
        self.split.append((token, market_id, amount))
        return {}


def test_bootstrap_registers_anchor_and_noise_bots(tmp_path: Path):
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=2,
    )
    bots = pool.ensure_provisioned(market_ids_for_inventory=[])
    assert len(bots) == 3
    assert [b.role for b in bots] == [BotRole.ANCHOR, BotRole.NOISE, BotRole.NOISE]
    # Every bot was marked.
    assert set(client.marked) == {b.creds.eth_address for b in bots}
    # creds.json persisted.
    saved = json.loads(creds.read_text())
    assert len(saved) == 3


def test_bootstrap_is_idempotent_via_creds_file(tmp_path: Path):
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps([
        {"name": "anchor-0", "role": "ANCHOR",
         "token": "tok-existing", "eth_address": "0xexisting", "email": "x@x"},
    ]))
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=0,
    )
    bots = pool.ensure_provisioned(market_ids_for_inventory=[])
    # No new registrations because the only required bot already exists.
    assert client.registered == []
    assert len(bots) == 1
    assert bots[0].creds.eth_address == "0xexisting"


def test_inventory_split_called_for_anchor_bots_only(tmp_path: Path):
    creds = tmp_path / "creds.json"
    client = FakeClient()
    pool = BotPool(
        client=client, creds_path=str(creds),
        anchor_pool_size=1, noise_pool_size=1, inventory_split_shares=500,
    )
    pool.ensure_provisioned(market_ids_for_inventory=[7, 11])
    # Anchor bot got 2 splits (one per market), noise bot got none.
    assert client.split == [("tok-0xa1", 7, 500), ("tok-0xa1", 11, 500)]
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_bot_pool.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `bot_pool.py`** — `agentpit_bots/bot_pool.py`:

```python
"""BotPool — registers, persists, and provisions bot identities.

Roles:
- ANCHOR: one or a few bots that run AnchorMarketMaker. Need inventory
  per market (split a complete set so they can post SELL orders).
- NOISE: bots that run NoiseTrader. No per-market inventory — they
  acquire via MINT matches as they trade.

Bot identities are persisted in ``creds_path`` (JSON list). On startup
the pool reads existing entries and only registers what's missing.
"""
from __future__ import annotations

import enum
import json
import logging
import secrets
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from agentpit_bots.client import BotCredentials

log = logging.getLogger(__name__)


class BotRole(str, enum.Enum):
    ANCHOR = "ANCHOR"
    NOISE = "NOISE"


@dataclass
class Bot:
    name: str
    role: BotRole
    creds: BotCredentials


def _make_email(name: str) -> str:
    # Random suffix prevents collision with any user that registered manually.
    return f"bot-{name}-{secrets.token_hex(4)}@agentpit.internal"


_BOT_PASSWORD = "bot-default-pw-32-chars-min-length"   # >= 8 chars; never exposed


class BotPool:
    def __init__(
        self,
        *,
        client,
        creds_path: str,
        anchor_pool_size: int,
        noise_pool_size: int,
        inventory_split_shares: int = 500,
    ):
        self._client = client
        self._creds_path = Path(creds_path)
        self._anchor_pool_size = anchor_pool_size
        self._noise_pool_size = noise_pool_size
        self._inventory_split_shares = inventory_split_shares

    def ensure_provisioned(
        self, *, market_ids_for_inventory: Iterable[int]
    ) -> list[Bot]:
        existing = self._load_existing()
        existing_by_name = {b["name"]: b for b in existing}

        want: list[tuple[str, BotRole]] = [
            (f"anchor-{i}", BotRole.ANCHOR) for i in range(self._anchor_pool_size)
        ] + [
            (f"noise-{i}", BotRole.NOISE) for i in range(self._noise_pool_size)
        ]

        bots: list[Bot] = []
        new_entries: list[dict] = list(existing)
        for name, role in want:
            if name in existing_by_name:
                e = existing_by_name[name]
                bots.append(Bot(
                    name=name, role=BotRole(e["role"]),
                    creds=BotCredentials(token=e["token"], eth_address=e["eth_address"]),
                ))
                continue
            email = _make_email(name)
            creds = self._client.register(email=email, password=_BOT_PASSWORD)
            self._client.mark_bot(eth_address=creds.eth_address)
            bots.append(Bot(name=name, role=role, creds=creds))
            new_entries.append({
                "name": name, "role": role.value,
                "token": creds.token, "eth_address": creds.eth_address,
                "email": email,
            })
            log.info("registered_bot name=%s role=%s eth=%s",
                     name, role.value, creds.eth_address)

        self._save(new_entries)

        # Inventory split for anchor bots.
        market_ids = list(market_ids_for_inventory)
        for bot in bots:
            if bot.role != BotRole.ANCHOR:
                continue
            for market_id in market_ids:
                try:
                    self._client.split_position(
                        token=bot.creds.token, market_id=market_id,
                        amount=self._inventory_split_shares,
                    )
                except Exception as exc:
                    log.warning(
                        "split_position_failed bot=%s market_id=%s err=%s",
                        bot.name, market_id, exc,
                    )
        return bots

    def _load_existing(self) -> list[dict]:
        if not self._creds_path.exists():
            return []
        try:
            return json.loads(self._creds_path.read_text())
        except (ValueError, OSError) as exc:
            log.warning("creds_load_failed path=%s err=%s", self._creds_path, exc)
            return []

    def _save(self, entries: list[dict]) -> None:
        self._creds_path.parent.mkdir(parents=True, exist_ok=True)
        self._creds_path.write_text(json.dumps(entries, indent=2))
```

- [ ] **Step 4: Run bot pool tests**

Run: `pytest -s tests/bots/test_bot_pool.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/bot_pool.py tests/bots/test_bot_pool.py
git commit -m "bots: BotPool — idempotent registration, marking, and inventory split"
```

---

## Task 12: `Runner` — main loop wiring everything together

**Files:**
- Create: `agentpit_bots/runner.py`
- Test: `tests/bots/test_runner.py`

The runner is the only piece with real concurrency. Keep it deterministic by accepting an injected scheduler and a `now_fn`.

- [ ] **Step 1: Write the failing test** — `tests/bots/test_runner.py`

```python
"""Runner: discovers markets, loops bots, posts via the injected client.

The runner is wired with fakes here so tests are deterministic.
"""
import random

from agentpit_bots.bot_pool import Bot, BotRole
from agentpit_bots.client import BotCredentials
from agentpit_bots.config import BotConfig
from agentpit_bots.runner import Runner


class FakeOracle:
    def __init__(self, mids: dict[str, float]):
        self._mids = mids
        self.refreshed_with: list[list[str]] = []

    def refresh(self, token_ids):
        self.refreshed_with.append(list(token_ids))
        return self

    def midpoint(self, token_id):
        return self._mids.get(token_id)

    def is_stale(self, token_id, *, stale_after_sec, now=None):
        return False


class FakeClient:
    def __init__(self, markets, my_orders):
        self._markets = markets
        self._my_orders = my_orders
        self.placed: list[dict] = []
        self.cancelled: list[str] = []

    def get_markets(self):
        return self._markets

    def list_my_orders(self, *, token):
        return list(self._my_orders.get(token, []))

    def place_order(self, *, token, market_id, outcome, side, price, size):
        self.placed.append({
            "token": token, "market_id": market_id, "outcome": outcome,
            "side": side, "price": price, "size": size,
        })
        return {"orderID": f"new-{len(self.placed)}", "status": "live",
                "success": True, "filledSize": "0", "remainingSize": str(size)}

    def cancel_order(self, *, token, order_id):
        self.cancelled.append(order_id)
        return {"order_id": order_id, "status": "cancelled"}


def _bot(name, role):
    return Bot(name=name, role=BotRole(role),
               creds=BotCredentials(token=f"tok-{name}", eth_address=f"0x{name}"))


def test_runner_tick_places_anchor_quotes():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({"poly-yes": 0.50})
    client = FakeClient(markets=markets, my_orders={})
    bots = [_bot("anchor-0", "ANCHOR")]
    cfg = BotConfig(mm_half_spread_usd=0.01, mm_quote_size_shares=100)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=bots)

    runner.run_anchor_tick()

    # Four orders posted: YES BUY, YES SELL, NO BUY, NO SELL.
    assert len(client.placed) == 4
    yes_buy = next(p for p in client.placed if p["side"] == "BUY" and p["outcome"] == "Yes")
    yes_sell = next(p for p in client.placed if p["side"] == "SELL" and p["outcome"] == "Yes")
    assert yes_buy["price"] == "0.49"
    assert yes_sell["price"] == "0.51"


def test_runner_skips_markets_without_upstream_token_ids():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": None,
        "polymarket_no_token_id": None,
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_anchor_tick()
    assert client.placed == []


def test_runner_noise_tick_emits_one_order_per_noise_bot():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClient(markets=markets, my_orders={})
    cfg = BotConfig()
    bots = [_bot("noise-0", "NOISE"), _bot("noise-1", "NOISE")]
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=bots,
                    rng=random.Random(0))
    runner.run_noise_tick()
    assert len(client.placed) == 2  # one per noise bot


def test_runner_disabled_market_skipped():
    markets = [{
        "market_id": 99, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    cfg = BotConfig(disabled_market_ids=frozenset({99}))
    client = FakeClient(markets=markets, my_orders={})
    oracle = FakeOracle({"poly-yes": 0.5})
    runner = Runner(client=client, oracle=oracle, cfg=cfg,
                    bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_anchor_tick()
    assert client.placed == []
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_runner.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement `runner.py`**

`agentpit_bots/runner.py`:

```python
"""Bot runner: ticks the anchor and noise loops.

Run as: ``python -m agentpit_bots.runner --base http://localhost:8000``

The runner is decomposed so unit tests can call ``run_anchor_tick`` and
``run_noise_tick`` directly without spinning up the time-based loop.
"""
from __future__ import annotations

import argparse
import logging
import random
import time
from dataclasses import dataclass

from agentpit_bots.bot_pool import Bot, BotPool, BotRole
from agentpit_bots.client import AgentpitClient
from agentpit_bots.config import BotConfig, DEFAULT, SHARES_SCALE
from agentpit_bots.price_oracle import PriceOracle
from agentpit_bots.reconcile import DesiredOrder, LiveOrder, reconcile
from agentpit_bots.strategies.anchor_mm import AnchorMarketMaker, _PRICE_SCALE
from agentpit_bots.strategies.base import MarketTokens
from agentpit_bots.strategies.noise_trader import NoiseTrader

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MarketView:
    market_id: int
    yes_local: str
    no_local: str
    yes_outcome_label: str   # e.g. "Yes" — needed for /orders body
    no_outcome_label: str
    poly_yes_token_id: str | None
    poly_no_token_id: str | None


class Runner:
    def __init__(
        self,
        *,
        client,
        oracle,
        cfg: BotConfig,
        bots: list[Bot],
        rng: random.Random | None = None,
    ):
        self._client = client
        self._oracle = oracle
        self._cfg = cfg
        self._bots = bots
        self._rng = rng or random.Random()
        self._anchor_strat = AnchorMarketMaker(cfg)
        self._noise_strat = NoiseTrader(cfg, rng=self._rng)

    # --- public tick entry points --------------------------------------

    def run_anchor_tick(self) -> None:
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for bot in self._bots:
            if bot.role != BotRole.ANCHOR:
                continue
            self._anchor_tick_for_bot(bot, markets)

    def run_noise_tick(self) -> None:
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for bot in self._bots:
            if bot.role != BotRole.NOISE:
                continue
            market = self._rng.choice(markets)
            self._noise_tick_for_bot(bot, market)

    # --- per-bot loops -------------------------------------------------

    def _anchor_tick_for_bot(self, bot: Bot, markets: list[_MarketView]) -> None:
        live_orders = self._fetch_live_orders(bot)
        for m in markets:
            mid = self._oracle.midpoint(m.poly_yes_token_id) if m.poly_yes_token_id else None
            if mid is None:
                log.info("oracle_stale market_id=%s", m.market_id)
                continue
            desired = self._anchor_strat.compute_desired_orders(
                market=MarketTokens(
                    market_id=m.market_id,
                    yes_token_id=m.yes_local,
                    no_token_id=m.no_local,
                ),
                poly_yes_mid=mid,
            )
            live_for_market = [
                lo for lo in live_orders
                if lo.token_id in (m.yes_local, m.no_local)
            ]
            cancels, creates = reconcile(live_for_market, desired)
            for cid in cancels:
                self._safe_cancel(bot, cid)
            for create in creates:
                self._safe_place(bot, create, m)

    def _noise_tick_for_bot(self, bot: Bot, market: _MarketView) -> None:
        mid = self._oracle.midpoint(market.poly_yes_token_id) if market.poly_yes_token_id else None
        if mid is None:
            return
        desired = self._noise_strat.compute_desired_orders(
            market=MarketTokens(
                market_id=market.market_id,
                yes_token_id=market.yes_local,
                no_token_id=market.no_local,
            ),
            poly_yes_mid=mid,
        )
        for d in desired:
            self._safe_place(bot, d, market)

    # --- helpers --------------------------------------------------------

    def _discover_markets(self, *, require_upstream_tokens: bool) -> list[_MarketView]:
        raw = self._client.get_markets()
        out: list[_MarketView] = []
        for m in raw:
            if m.get("market_state") != "ACTIVE":
                continue
            if int(m["market_id"]) in self._cfg.disabled_market_ids:
                continue
            tokens = m.get("erc1155_tokens") or []
            if len(tokens) != 2:
                continue
            yes_local = no_local = None
            yes_label = no_label = None
            for tok_id, label in tokens:
                if str(label).lower() == "yes":
                    yes_local = str(tok_id); yes_label = str(label)
                elif str(label).lower() == "no":
                    no_local = str(tok_id); no_label = str(label)
            if not (yes_local and no_local):
                continue
            poly_yes = m.get("polymarket_yes_token_id")
            poly_no = m.get("polymarket_no_token_id")
            if require_upstream_tokens and not (poly_yes and poly_no):
                continue
            out.append(_MarketView(
                market_id=int(m["market_id"]),
                yes_local=yes_local, no_local=no_local,
                yes_outcome_label=yes_label, no_outcome_label=no_label,
                poly_yes_token_id=poly_yes, poly_no_token_id=poly_no,
            ))
        return out

    def _refresh_oracle(self, markets: list[_MarketView]) -> None:
        token_ids = [m.poly_yes_token_id for m in markets if m.poly_yes_token_id]
        self._oracle.refresh(token_ids)

    def _fetch_live_orders(self, bot: Bot) -> list[LiveOrder]:
        try:
            raw = self._client.list_my_orders(token=bot.creds.token)
        except Exception as exc:
            log.warning("list_my_orders_failed bot=%s err=%s", bot.name, exc)
            return []
        result: list[LiveOrder] = []
        for r in raw:
            try:
                result.append(LiveOrder(
                    order_id=r["ORDER_ID"], side=r["SIDE"],
                    token_id=str(r["TOKEN_ID"]),
                    price_int=int(r["PRICE"]),
                    remaining_amount=int(r["REMAINING_AMOUNT"]),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _safe_place(self, bot: Bot, d: DesiredOrder, market: _MarketView) -> None:
        # token_id → outcome label so we can send "Yes"/"No" to /orders
        if d.token_id == market.yes_local:
            outcome = market.yes_outcome_label
        elif d.token_id == market.no_local:
            outcome = market.no_outcome_label
        else:
            log.warning("unknown_token_id token=%s market=%s", d.token_id, market.market_id)
            return
        price_str = f"{d.price_int / _PRICE_SCALE:.2f}"
        try:
            self._client.place_order(
                token=bot.creds.token,
                market_id=market.market_id,
                outcome=outcome, side=d.side,
                price=price_str, size=d.size,
            )
        except Exception as exc:
            log.warning(
                "place_failed bot=%s market=%s side=%s outcome=%s err=%s",
                bot.name, market.market_id, d.side, outcome, exc,
            )

    def _safe_cancel(self, bot: Bot, order_id: str) -> None:
        try:
            self._client.cancel_order(token=bot.creds.token, order_id=order_id)
        except Exception as exc:
            log.warning("cancel_failed bot=%s order=%s err=%s", bot.name, order_id, exc)


# --- entry point --------------------------------------------------------

def _build_runner(cfg: BotConfig) -> tuple[Runner, BotPool, list[int]]:
    import requests
    from py_clob_client.client import ClobClient

    session = requests.Session()
    ap_client = AgentpitClient(
        base_url=cfg.base_url, session=session, admin_token=cfg.admin_token,
    )
    clob = ClobClient(host=cfg.polymarket_clob_host)
    oracle = PriceOracle(clob=clob)

    pool = BotPool(
        client=ap_client, creds_path=cfg.creds_path,
        anchor_pool_size=cfg.anchor_pool_size,
        noise_pool_size=cfg.noise_pool_size,
        inventory_split_shares=cfg.inventory_split_shares,
    )
    markets = [m for m in ap_client.get_markets()
               if m.get("market_state") == "ACTIVE"
               and m.get("polymarket_yes_token_id")
               and m.get("polymarket_no_token_id")]
    market_ids = [int(m["market_id"]) for m in markets]
    bots = pool.ensure_provisioned(market_ids_for_inventory=market_ids)
    return Runner(client=ap_client, oracle=oracle, cfg=cfg, bots=bots), pool, market_ids


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT.base_url)
    ap.add_argument("--tick", type=int, default=DEFAULT.tick_interval_sec)
    args = ap.parse_args()

    cfg = BotConfig(base_url=args.base, tick_interval_sec=args.tick)
    runner, _pool, _market_ids = _build_runner(cfg)

    log.info("bot_runner_starting tick_sec=%s", cfg.tick_interval_sec)
    tick_index = 0
    last_noise = 0.0
    while True:
        try:
            runner.run_anchor_tick()
            now = time.time()
            if now - last_noise >= cfg.noise_tick_base_sec:
                runner.run_noise_tick()
                last_noise = now
            tick_index += 1
        except Exception:
            log.exception("tick_failed")
        time.sleep(cfg.tick_interval_sec)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run runner tests**

Run: `pytest -s tests/bots/test_runner.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/runner.py tests/bots/test_runner.py
git commit -m "bots: Runner orchestrating anchor + noise ticks via injected client/oracle"
```

---

## Task 13: End-to-end manual smoke + drift logging

**Files:**
- Modify: `agentpit_bots/runner.py` (add drift logging)
- Test: `tests/bots/test_runner.py` (append)

- [ ] **Step 1: Write the failing test for drift logging** — append to `tests/bots/test_runner.py`:

```python
def test_runner_emits_drift_log_per_market(caplog):
    """log_drift logs (market_id, local_mid, poly_mid, drift) for each enabled market."""
    import logging as _logging

    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    oracle = FakeOracle({"poly-yes": 0.42})
    client = FakeClient(markets=markets, my_orders={})

    class FakeBookClient(FakeClient):
        def get_orderbook(self, *, market_id, outcome):
            return {"bids": [{"PRICE": 400_000}], "asks": [{"PRICE": 440_000}]}

    book_client = FakeBookClient(markets=markets, my_orders={})
    cfg = BotConfig()
    runner = Runner(client=book_client, oracle=oracle, cfg=cfg, bots=[])
    with caplog.at_level(_logging.INFO, logger="agentpit_bots.runner"):
        runner.log_drift()
    assert any("drift" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_runner.py::test_runner_emits_drift_log_per_market -v`
Expected: FAIL (`log_drift` doesn't exist).

- [ ] **Step 3: Add `log_drift` to `Runner`**

In `agentpit_bots/runner.py`, add to the `Runner` class:

```python
    def log_drift(self) -> None:
        """Log local vs polymarket mid for every enabled market.

        Local mid = average of best bid + best ask from /orderbook. Skipped
        when one side is empty.
        """
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        self._refresh_oracle(markets)
        for m in markets:
            poly_mid = self._oracle.midpoint(m.poly_yes_token_id) if m.poly_yes_token_id else None
            if poly_mid is None:
                continue
            try:
                book = self._client.get_orderbook(
                    market_id=m.market_id, outcome=m.yes_outcome_label,
                )
            except Exception:
                continue
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            if not bids or not asks:
                log.info(
                    "drift market_id=%s local_mid=none poly_mid=%.4f",
                    m.market_id, poly_mid,
                )
                continue
            local_mid = (int(bids[0]["PRICE"]) + int(asks[0]["PRICE"])) / 2 / _PRICE_SCALE
            log.info(
                "drift market_id=%s local_mid=%.4f poly_mid=%.4f drift_cents=%+.2f",
                m.market_id, local_mid, poly_mid, (local_mid - poly_mid) * 100,
            )
```

In `main()`, add inside the loop after `runner.run_anchor_tick()`:

```python
            if tick_index % max(1, 60 // cfg.tick_interval_sec) == 0:
                runner.log_drift()
```

- [ ] **Step 4: Run drift test**

Run: `pytest -s tests/bots/test_runner.py::test_runner_emits_drift_log_per_market -v`
Expected: PASS.

- [ ] **Step 5: Run full bot test suite**

Run: `pytest -s tests/bots/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit_bots/runner.py tests/bots/test_runner.py
git commit -m "bots: log local-vs-Polymarket drift once per minute"
```

---

## Task 14: Manual smoke test

This task is a guided manual verification — no automated assertions.

- [ ] **Step 1: Start Anvil + the AgentPit server**

In separate terminals:

```bash
./scripts/run_node.sh
./scripts/deploy_exchange.sh
AGENTPIT_DB_PATH=/tmp/bots-smoke.db uvicorn agentpit.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- [ ] **Step 2: Sync a few markets from Polymarket**

```bash
python -c "
import sqlite3
from agentpit.config import Settings
from agentpit.onchain.admin_factory import build_onchain_admin   # adjust if helper name differs
from agentpit.polymarket.polymarket_sync import fetch_and_sync_polymarket_markets
db = sqlite3.connect('/tmp/bots-smoke.db')
admin = build_onchain_admin(Settings())
created = fetch_and_sync_polymarket_markets(db, admin)
print(f'synced {len(created)} markets')
"
```

If the admin-builder helper name differs from `build_onchain_admin`, locate the equivalent factory via `grep -rn 'OnchainAdmin(' agentpit/` and use it.

- [ ] **Step 3: Start the bot runner**

```bash
AGENTPIT_ADMIN_TOKEN=dev-admin-token python -m agentpit_bots.runner --base http://localhost:8000 --tick 30
```

- [ ] **Step 4: Verify bot activity**

Open a third terminal:

```bash
# Should show bot orders within ~30s of runner start
curl -s http://localhost:8000/markets | python3 -m json.tool | head -20
curl -s http://localhost:8000/orderbook/<MARKET_ID>/Yes | python3 -m json.tool

# Check the runner logs for drift lines:
#   drift market_id=... local_mid=... poly_mid=... drift_cents=...
# After 2-3 ticks the drift should be small (within ¢5).
```

- [ ] **Step 5: Stop the runner** — Ctrl-C is enough. `creds.json` persists; re-running picks up the same bots.

No commit for this task — manual verification only.

---

## Self-Review

**Spec coverage:**

- Goals §2: anchor within ¢2 of Polymarket → covered by Tasks 9, 12; drift verified in Task 14 and via Task 13 `log_drift`.
- Resting bids/asks per market → Task 9 (AnchorMarketMaker generates 4 desired orders).
- Trades per minute → Task 10 (NoiseTrader) + Task 12 noise tick loop.
- External service, public REST → Task 8 client + Task 12 runner uses only the public API + `/admin/mark_bot`.
- Architecture §3 external service decision → Task 12.
- Components §4 file layout → matches Tasks 5-12.
- Strategy 5.1 anchor + rebalance + graceful degradation → Tasks 9, 12. Inventory rebalance described in spec §5.1 but NOT implemented as a separate task — flagged below.
- Strategy 5.2 noise → Task 10.
- Oracle §6 batched/cached/graceful → Task 7.
- Bot pool §7 register/mark/split → Task 11.
- Schema additions §8 → Task 1.
- Configuration §9 → Task 5 `BotConfig`.
- Data flow §10 → Task 12 `_anchor_tick_for_bot`.
- Failure handling §11 → Task 7 stale handling + Task 12 safe_place/safe_cancel.
- Observability §12 → Tasks 12/13 structured logs.
- Testing §13 → unit tests in Tasks 6-12, manual smoke in Task 14.

**Gap:** Spec §5.1 calls for inventory rebalance every 10th tick (call `merge_positions` on surplus). Not implemented in current tasks. Adding as Task 12b below.

**Gap:** Spec §11 "bot runs out of one outcome → split_position at tick start" is also not implemented. Adding to Task 12b.

**Placeholder scan:** No "TBD" / "TODO" / vague-handler instructions remain. Every code step shows the actual code.

**Type consistency:**
- `BotCredentials` used in Tasks 8 + 11 + 12 — consistent (`token`, `eth_address`).
- `LiveOrder` / `DesiredOrder` shape consistent between Task 6, 9, 10, 12.
- `MarketTokens` used in 9 + 10 + 12 — same `market_id`, `yes_token_id`, `no_token_id` fields.
- `BotConfig` field names consistent across 5, 9, 10, 11, 12.

---

## Task 12b: Inventory rebalance + depletion top-up

**Files:**
- Modify: `agentpit_bots/runner.py`
- Test: `tests/bots/test_runner.py` (append)

- [ ] **Step 1: Add failing tests** — append to `tests/bots/test_runner.py`:

```python
class FakeClientWithPortfolio(FakeClient):
    def __init__(self, markets, my_orders, portfolio):
        super().__init__(markets, my_orders)
        self._portfolio = portfolio
        self.merged: list[tuple[int, int]] = []
        self.split: list[tuple[int, int]] = []

    def get_portfolio(self, *, token):
        return self._portfolio

    def merge_positions(self, *, token, market_id, amount):
        self.merged.append((market_id, amount))
        return {}

    def split_position(self, *, token, market_id, amount):
        self.split.append((market_id, amount))
        return {}


def test_rebalance_merges_when_both_sides_have_surplus():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 800 * 1_000_000},
            {"market_id": 1, "token_id": "local-no",  "balance": 700 * 1_000_000},
        ],
    }
    cfg = BotConfig(mm_rebalance_floor_shares=200)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_rebalance_tick()
    # min(yes, no) = 700; surplus = 700 - 200 = 500 → merge 500.
    assert client.merged == [(1, 500)]


def test_split_when_one_side_depleted():
    markets = [{
        "market_id": 1, "market_state": "ACTIVE",
        "polymarket_yes_token_id": "poly-yes",
        "polymarket_no_token_id": "poly-no",
        "erc1155_tokens": [["local-yes", "Yes"], ["local-no", "No"]],
    }]
    portfolio = {
        "usdc_balance": 5000,
        "positions": [
            {"market_id": 1, "token_id": "local-yes", "balance": 50 * 1_000_000},
            {"market_id": 1, "token_id": "local-no",  "balance": 5 * 1_000_000},   # depleted
        ],
    }
    cfg = BotConfig(mm_quote_size_shares=100)
    oracle = FakeOracle({"poly-yes": 0.5})
    client = FakeClientWithPortfolio(markets=markets, my_orders={}, portfolio=portfolio)
    runner = Runner(client=client, oracle=oracle, cfg=cfg, bots=[_bot("anchor-0", "ANCHOR")])
    runner.run_rebalance_tick()
    # min(yes, no) = 5 < quote_size 100 → re-split a complete set of quote_size.
    assert client.split == [(1, 100)]
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest -s tests/bots/test_runner.py::test_rebalance_merges_when_both_sides_have_surplus -v`
Expected: FAIL (`run_rebalance_tick` doesn't exist).

- [ ] **Step 3: Add `run_rebalance_tick` to `Runner`** — in `agentpit_bots/runner.py`:

```python
    def run_rebalance_tick(self) -> None:
        """For each ANCHOR bot × market: merge surplus, split if depleted."""
        markets = self._discover_markets(require_upstream_tokens=True)
        if not markets:
            return
        market_by_id = {m.market_id: m for m in markets}
        for bot in self._bots:
            if bot.role != BotRole.ANCHOR:
                continue
            try:
                portfolio = self._client.get_portfolio(token=bot.creds.token)
            except Exception as exc:
                log.warning("portfolio_failed bot=%s err=%s", bot.name, exc)
                continue
            by_market: dict[int, dict[str, int]] = {}
            for pos in portfolio.get("positions", []):
                mid = int(pos.get("market_id", 0))
                if mid not in market_by_id:
                    continue
                tok = str(pos.get("token_id"))
                bal_shares = int(pos.get("balance", 0)) // SHARES_SCALE
                by_market.setdefault(mid, {})[tok] = bal_shares
            for mid, market in market_by_id.items():
                yes_bal = by_market.get(mid, {}).get(market.yes_local, 0)
                no_bal = by_market.get(mid, {}).get(market.no_local, 0)
                min_bal = min(yes_bal, no_bal)
                if min_bal < self._cfg.mm_quote_size_shares:
                    try:
                        self._client.split_position(
                            token=bot.creds.token, market_id=mid,
                            amount=self._cfg.mm_quote_size_shares,
                        )
                    except Exception as exc:
                        log.warning(
                            "split_failed bot=%s market=%s err=%s",
                            bot.name, mid, exc,
                        )
                    continue
                surplus = min_bal - self._cfg.mm_rebalance_floor_shares
                if surplus > 0:
                    try:
                        self._client.merge_positions(
                            token=bot.creds.token, market_id=mid, amount=surplus,
                        )
                    except Exception as exc:
                        log.warning(
                            "merge_failed bot=%s market=%s err=%s",
                            bot.name, mid, exc,
                        )
```

In `main()`, schedule the rebalance: track `tick_index` and call `runner.run_rebalance_tick()` every `mm_rebalance_every_ticks`:

```python
            if tick_index % cfg.mm_rebalance_every_ticks == 0:
                runner.run_rebalance_tick()
```

- [ ] **Step 4: Run the new tests**

Run: `pytest -s tests/bots/test_runner.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit_bots/runner.py tests/bots/test_runner.py
git commit -m "bots: rebalance tick — merge surplus and split when depleted"
```

---

## Done

When all 14 tasks (1-13 + 12b) are complete:

- Schema migration is live and round-trips upstream Polymarket token IDs.
- Two new endpoints exist: `POST /admin/mark_bot`, `GET /orders/mine`.
- The `agentpit_bots/` package runs as a standalone service.
- Manual smoke (Task 14) shows resting orders within ~30s and drift logs showing `drift_cents` within ¢5.

Total commits planned: 13 (one per task, plus Task 14 is no-commit, Task 12b is +1).
