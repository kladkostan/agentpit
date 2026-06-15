# agentpit backend prereqs (X-API-Key auth + idempotent orders) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add long-lived `X-API-Key` auth and idempotent `POST /order` to agentpit so an autonomous bot can run a 24/7 loop without re-login churn or double-placed orders.

**Architecture:** Two independent, additive features. (1) Auth: expose the existing per-user `api_key` and accept it via an `X-API-Key` header as an alternative credential alongside the unchanged JWT path. (2) Idempotency: an optional `client_order_id` on `POST /order`, deduped via a dedicated `idempotency_keys` table whose composite primary key is claimed inside the same transaction as the order insert (race-safe); duplicates replay the prior order via a reconstruction helper. Refines spec §5.4: the normal response path is left untouched (it returns in-memory tx hashes); only the *amount* computation is shared via a `_fill_amounts` helper, and replay assembles its own response from DB.

**Tech Stack:** Python, FastAPI, pydantic v2, psycopg (Postgres), pytest. Spec: `docs/superpowers/specs/2026-06-15-agentpit-trader-backend-prereqs-design.md`.

**Prerequisites to run tests:** local Postgres `agentpit_test`, anvil + deployed exchange (`./scripts/run_node.sh && ./scripts/deploy_exchange.sh`). Onchain tests auto-skip if the RPC is unreachable; DB/model tests do not need anvil.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `agentpit/datastructures/auth_response.py` | wire shape of `UserPublic` | add `api_key` field |
| `agentpit/services/auth_service.py` | builds `UserPublic` in `_issue` | pass `api_key` |
| `agentpit/auth/dependencies.py` | resolve a request credential to a `User` | add `X-API-Key` branch |
| `agentpit/datastructures/place_order_request.py` | order request shape | add optional `client_order_id` |
| `agentpit/db/table_create.py` | schema | add `idempotency_keys` table |
| `agentpit/db/table_write.py` | writes | `claim_idempotency_key`, `purge_idempotency_keys` |
| `agentpit/db/table_read.py` | reads | `get_idempotency_order_id` |
| `agentpit/services/order_service.py` | order placement | `_fill_amounts`, `_build_replay_response`, claim flow |
| `agentpit/config.py` | settings | `idempotency_key_retention_seconds` |
| `agentpit/api/app.py` | cleanup loop | purge idempotency keys |

---

## Task 1: Expose `api_key` in `UserPublic`

**Files:**
- Modify: `agentpit/datastructures/auth_response.py`
- Modify: `agentpit/services/auth_service.py:147-159`
- Test: `tests/api/test_auth.py`

- [ ] **Step 1: Write the failing test** (append to `tests/api/test_auth.py`)

```python
def test_register_exposes_api_key():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "apikey@example.com", "password": "hunter22hunter22"},
        ).json()
        assert body["user"]["api_key"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_auth.py::test_register_exposes_api_key -v`
Expected: FAIL — `KeyError: 'api_key'` (field not in the response).

- [ ] **Step 3: Add the field to `UserPublic`**

In `agentpit/datastructures/auth_response.py`, add `api_key` after `eth_address`:

```python
class UserPublic(BaseModel):
    user_id: str
    email: str
    handle: str | None
    eth_address: str
    api_key: str
    onboarded_at: int | None
    created_at: int
```

- [ ] **Step 4: Populate it in `_issue`**

In `agentpit/services/auth_service.py`, the `_issue` method builds `UserPublic` explicitly — add `api_key=user.api_key`:

```python
    def _issue(self, user: User) -> AuthResponse:
        token = self._coder.encode(user_id=user.user_id, email=user.email)
        return AuthResponse(
            access_token=token,
            user=UserPublic(
                user_id=user.user_id,
                email=user.email,
                handle=user.handle,
                eth_address=user.eth_address,
                api_key=user.api_key,
                onboarded_at=user.onboarded_at,
                created_at=user.created_at,
            ),
        )
```

(`GET /me` builds `UserPublic.model_validate(user.model_dump())`; `User` already has `api_key`, so it flows through with no change there.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/api/test_auth.py::test_register_exposes_api_key -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit/datastructures/auth_response.py agentpit/services/auth_service.py tests/api/test_auth.py
git commit -m "feat(auth): expose per-user api_key in UserPublic"
```

---

## Task 2: Accept `X-API-Key` in the auth dependency

**Files:**
- Modify: `agentpit/auth/dependencies.py`
- Test: `tests/api/test_auth.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/api/test_auth.py`)

```python
def test_me_accepts_api_key_header():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "akauth@example.com", "password": "hunter22hunter22"},
        ).json()
        api_key = body["user"]["api_key"]
        resp = client.get("/me", headers={"X-API-Key": api_key})
        assert resp.status_code == 200, resp.text
        assert resp.json()["email"] == "akauth@example.com"


def test_me_rejects_invalid_api_key():
    with TestClient(app) as client:
        resp = client.get("/me", headers={"X-API-Key": "nope-not-a-key"})
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_auth.py::test_me_accepts_api_key_header tests/api/test_auth.py::test_me_rejects_invalid_api_key -v`
Expected: `test_me_accepts_api_key_header` FAILS with 401 (header ignored); `test_me_rejects_invalid_api_key` happens to pass (no creds → 401) but keep it as a guard.

- [ ] **Step 3: Add the `X-API-Key` branch**

Rewrite `agentpit/auth/dependencies.py` to add an `APIKeyHeader` and a leading credential branch. Full file:

```python
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from agentpit.auth.jwt import JwtCoder
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def make_current_user_dep(coder: JwtCoder):
    """Build a FastAPI dependency that resolves a request credential to a User.

    Two accepted credentials: a long-lived `X-API-Key` header (checked first),
    or a bearer JWT (the original path, unchanged). The coder is captured by
    closure so tests can swap it via dependency_overrides.
    """
    from agentpit.api.deps import get_db_session

    def current_user(
        api_key: Annotated[str | None, Depends(_api_key_header)],
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        db: Annotated[DbSession, Depends(get_db_session)],
    ) -> User:
        if api_key:
            with db.read() as conn:
                user = TableRead.get_user_by_api_key(conn, api_key)
            if user is None:
                raise _unauth("invalid api key")
            return user

        if creds is None or not creds.credentials:
            raise _unauth("missing credentials")
        try:
            payload = coder.decode(creds.credentials)
        except jwt.ExpiredSignatureError:
            raise _unauth("token expired")
        except jwt.PyJWTError:
            raise _unauth("invalid token")

        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise _unauth("invalid token payload")

        with db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise _unauth("user no longer exists")
        return user

    return current_user
```

- [ ] **Step 4: Run tests to verify they pass** (and JWT path still works)

Run: `pytest tests/api/test_auth.py -v`
Expected: all PASS, including the existing `test_me_returns_current_user` (JWT) and `test_me_rejects_invalid_token`.

- [ ] **Step 5: Commit**

```bash
git add agentpit/auth/dependencies.py tests/api/test_auth.py
git commit -m "feat(auth): accept long-lived X-API-Key as an alternative credential"
```

---

## Task 3: Add optional `client_order_id` to `PlaceOrderRequest`

**Files:**
- Modify: `agentpit/datastructures/place_order_request.py:11-23`
- Test: `tests/test_place_order_request.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_place_order_request.py`)

```python
def test_client_order_id_optional_defaults_none():
    r = PlaceOrderRequest(token_id="123", side="BUY", price="0.5", size=1)
    assert r.client_order_id is None


def test_client_order_id_accepted():
    r = PlaceOrderRequest(
        token_id="123", side="BUY", price="0.5", size=1, client_order_id="abc"
    )
    assert r.client_order_id == "abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_place_order_request.py::test_client_order_id_accepted -v`
Expected: FAIL — pydantic ignores unknown `client_order_id` (or errors), `r.client_order_id` raises `AttributeError`.

- [ ] **Step 3: Add the field**

In `agentpit/datastructures/place_order_request.py`, add after `expiration`:

```python
    expiration: int = 0  # unix seconds, required if GTD
    client_order_id: str | None = None  # optional per-user idempotency key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_place_order_request.py -v`
Expected: all PASS (existing tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/place_order_request.py tests/test_place_order_request.py
git commit -m "feat(orders): optional client_order_id on PlaceOrderRequest"
```

---

## Task 4: `idempotency_keys` table + DB operations

**Files:**
- Modify: `agentpit/db/table_create.py` (add table method + register in `create_all_tables`)
- Modify: `agentpit/db/table_write.py` (claim + purge)
- Modify: `agentpit/db/table_read.py` (lookup)
- Test: `tests/db/test_idempotency.py` (create)

- [ ] **Step 1: Write the failing tests** (create `tests/db/test_idempotency.py`)

```python
"""idempotency_keys: a (api_key, client_order_id) claim is unique per user,
looks up its order id, and is purged by age."""

import psycopg
import pytest

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def test_claim_is_unique_and_looked_up():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k1", client_order_id="c1", order_id="0xaaa", created_at=100
        )
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k1", "c1") == "0xaaa"

    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.write() as conn:
            TableWrite.claim_idempotency_key(
                conn, api_key="k1", client_order_id="c1", order_id="0xbbb",
                created_at=200,
            )

    # Same client_order_id under a different api_key is independent.
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k2", client_order_id="c1", order_id="0xccc", created_at=100
        )
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k2", "c1") == "0xccc"


def test_get_idempotency_order_id_missing_returns_none():
    db = DbSession(Settings().database_url)
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "nope", "nope") is None


def test_purge_idempotency_keys_removes_old():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="old", order_id="0x1", created_at=100
        )
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="new", order_id="0x2", created_at=900
        )
        removed = TableWrite.purge_idempotency_keys(conn, before_ts=500)
    assert removed == 1
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k", "old") is None
        assert TableRead.get_idempotency_order_id(conn, "k", "new") == "0x2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_idempotency.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'claim_idempotency_key'` (and the table does not exist).

- [ ] **Step 3: Add the table** to `agentpit/db/table_create.py`

Add this method to the `TableCreate` class:

```python
    @staticmethod
    def create_idempotency_keys_table(conn: psycopg.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                API_KEY         TEXT   NOT NULL,
                CLIENT_ORDER_ID TEXT   NOT NULL,
                ORDER_ID        TEXT   NOT NULL,
                CREATED_AT      BIGINT NOT NULL,
                PRIMARY KEY (API_KEY, CLIENT_ORDER_ID)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_created_at "
            "ON idempotency_keys(CREATED_AT)"
        )
```

Register it in `create_all_tables` (add the line):

```python
    @staticmethod
    def create_all_tables(conn: psycopg.Connection) -> None:
        # errors propagate; no exception handling here
        TableCreate.create_orders_table(conn)
        TableCreate.create_trades_table(conn)
        TableCreate.create_users_table(conn)
        TableCreate.create_agents_table(conn)
        TableCreate.create_personalities_table(conn)
        TableCreate.create_events_table(conn)
        TableCreate.create_markets_table(conn)
        TableCreate.create_transactions_table(conn)
        TableCreate.create_price_snapshots_table(conn)
        TableCreate.create_idempotency_keys_table(conn)
```

- [ ] **Step 4: Add the writes** to `agentpit/db/table_write.py` (in the `TableWrite` class, near `purge_cancelled_orders`)

```python
    @staticmethod
    def claim_idempotency_key(
        db: psycopg.Connection,
        *,
        api_key: str,
        client_order_id: str,
        order_id: str,
        created_at: int,
    ) -> None:
        """Reserve (api_key, client_order_id) for this order. Raises
        psycopg.errors.UniqueViolation if already claimed — the caller treats
        that as a duplicate and replays the prior order."""
        db.execute(
            "INSERT INTO idempotency_keys "
            "(API_KEY, CLIENT_ORDER_ID, ORDER_ID, CREATED_AT) "
            "VALUES (%s, %s, %s, %s)",
            (api_key, client_order_id, order_id, created_at),
        )

    @staticmethod
    def purge_idempotency_keys(db: psycopg.Connection, before_ts: int) -> int:
        """Delete idempotency keys created before `before_ts`. Returns rows removed."""
        cur = db.execute(
            "DELETE FROM idempotency_keys WHERE CREATED_AT < %s",
            (before_ts,),
        )
        return cur.rowcount
```

- [ ] **Step 5: Add the read** to `agentpit/db/table_read.py` (in the `TableRead` class, near `get_user_by_api_key`)

```python
    @staticmethod
    def get_idempotency_order_id(
        db: psycopg.Connection, api_key: str, client_order_id: str
    ) -> "str | None":
        row = db.execute(
            "SELECT ORDER_ID FROM idempotency_keys "
            "WHERE API_KEY = %s AND CLIENT_ORDER_ID = %s",
            (api_key, client_order_id),
        ).fetchone()
        return row["ORDER_ID"] if row else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/db/test_idempotency.py -v`
Expected: all PASS. (The schema is created at conftest boot via `create_all_tables`.)

- [ ] **Step 7: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_write.py agentpit/db/table_read.py tests/db/test_idempotency.py
git commit -m "feat(db): idempotency_keys table with race-safe claim + purge"
```

---

## Task 5: Wire idempotency into `place_order`

**Files:**
- Modify: `agentpit/services/order_service.py` (imports, `place_order`, `_fill_amounts`, `_build_replay_response`)
- Test: `tests/onchain/test_idempotency.py`

- [ ] **Step 1: Write the failing tests** (create `tests/onchain/test_idempotency.py`)

```python
"""POST /order idempotency: a repeated client_order_id replays the first order
instead of placing a second; absent client_order_id keeps legacy behavior."""

from tests.onchain._helpers import create_market, fresh_client, register, hdr


def _yes(market) -> str:
    return market["erc1155_tokens"][0][0]


def test_same_client_order_id_places_once():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    body = {
        "token_id": yes, "side": "BUY", "price": "0.40", "size": 10,
        "client_order_id": "coid-abc",
    }
    r1 = client.post("/order", headers=hdr(tok), json=body).json()
    r2 = client.post("/order", headers=hdr(tok), json=body).json()
    assert r1["orderID"] == r2["orderID"]

    orders = client.get("/data/orders", headers=hdr(tok)).json()
    assert len([o for o in orders if o["asset_id"] == yes]) == 1


def test_absent_client_order_id_allows_two_orders():
    client = fresh_client()
    tok = register(client)["access_token"]
    market = create_market(client)
    yes = _yes(market)
    body = {"token_id": yes, "side": "BUY", "price": "0.40", "size": 10}
    o1 = client.post("/order", headers=hdr(tok), json=body).json()["orderID"]
    o2 = client.post("/order", headers=hdr(tok), json=body).json()["orderID"]
    assert o1 != o2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/onchain/test_idempotency.py -v`
Expected: `test_same_client_order_id_places_once` FAILS — two distinct `orderID`s and two live orders (no dedup yet). (Requires anvil; if it skips, start the node first.)

- [ ] **Step 3: Ensure imports** at the top of `agentpit/services/order_service.py`

Ensure these imports are present (add any that are missing):

```python
import time
import psycopg
```

- [ ] **Step 4: Extract `_fill_amounts`** and use it in the normal path

Add this static helper to the `OrderService` class:

```python
    @staticmethod
    def _fill_amounts(side: str, price_int: int, filled_micro: int) -> tuple[str, str]:
        """(makingAmount, takingAmount) decimal strings for a taker's fills, or
        ("","") when nothing filled. The taker transacts at its OWN limit price
        for every fill, so collateral is taker_price x filled."""
        if filled_micro <= 0:
            return "", ""
        collateral_micro = (price_int * filled_micro) // _PRICE_ONE
        if side == "BUY":
            return (
                size_to_decimal_str(collateral_micro),  # USDC given
                size_to_decimal_str(filled_micro),       # shares received
            )
        return (
            size_to_decimal_str(filled_micro),           # shares given
            size_to_decimal_str(collateral_micro),       # USDC received
        )
```

Replace the inline amount computation in `place_order` (currently the block that
computes `filled_micro`, `collateral_micro`, and the `making_amount/taking_amount`
if/elif/else) with:

```python
        filled_micro = sum(int(m["trade_size"]) for m in matches)
        making_amount, taking_amount = self._fill_amounts(
            payload.side, price_int, filled_micro
        )
```

- [ ] **Step 5: Add `_build_replay_response`**

Add this method to `OrderService`:

```python
    def _build_replay_response(self, conn, order_id: str) -> OrderResponse:
        """Reconstruct an OrderResponse for an already-placed order (idempotent
        replay). Fill amounts + trade ids come from the order's confirmed trades;
        transaction hashes are best-effort (the normal path returns them from the
        in-memory settlement, so DB rows may not carry them)."""
        row = self._get_order_row(conn, order_id)
        trades = conn.execute(
            "SELECT TRADE_ID, TRADE_SIZE, TRANSACTION_HASH, STATUS FROM trades "
            "WHERE TAKER_ORDER_ID = %s",
            (order_id,),
        ).fetchall()
        # Settlement is all-or-nothing per taker, so any FAILED trade means the
        # original attempt failed -> replay that failure (spec §5.5). errorMsg
        # is not reconstructed (the exception text was never persisted).
        has_failed = any(t["STATUS"] == "FAILED" for t in trades)
        confirmed = [t for t in trades if t["STATUS"] != "FAILED"]
        filled_micro = sum(int(t["TRADE_SIZE"]) for t in confirmed)
        making_amount, taking_amount = self._fill_amounts(
            row["SIDE"], int(row["PRICE"]), filled_micro
        )
        tx_hashes = [t["TRANSACTION_HASH"] for t in confirmed if t["TRANSACTION_HASH"]]
        return OrderResponse(
            success=not has_failed,
            orderID=order_id,
            status=row["STATUS"],
            transactionsHashes=tx_hashes,
            takingAmount=taking_amount,
            makingAmount=making_amount,
            tradeIDs=[t["TRADE_ID"] for t in confirmed],
        )
```

- [ ] **Step 6: Add the claim flow** to `place_order`

At the very start of `place_order` (before `_resolve_token`), add the fast-path:

```python
        coid = payload.client_order_id
        if coid is not None:
            with self._db.read() as conn:
                existing = TableRead.get_idempotency_order_id(conn, user.api_key, coid)
                if existing is not None:
                    return self._build_replay_response(conn, existing)
```

Then wrap the existing order-insert write block to claim the key atomically and
catch the concurrent-duplicate race. The block currently reads:

```python
        with self._db.write() as conn:
            self._insert_order(
                conn,
                api_key=user.api_key,
                order=order,
                order_id=order_id,
                signature=signature,
                price_int=price_int,
                order_type=payload.order_type,
            )
            taker_row = self._get_order_row(conn, order_id)
            matches = self._match(conn, taker_row, dry_run=False)
```

Replace it with:

```python
        try:
            with self._db.write() as conn:
                if coid is not None:
                    TableWrite.claim_idempotency_key(
                        conn,
                        api_key=user.api_key,
                        client_order_id=coid,
                        order_id=order_id,
                        created_at=int(time.time()),
                    )
                self._insert_order(
                    conn,
                    api_key=user.api_key,
                    order=order,
                    order_id=order_id,
                    signature=signature,
                    price_int=price_int,
                    order_type=payload.order_type,
                )
                taker_row = self._get_order_row(conn, order_id)
                matches = self._match(conn, taker_row, dry_run=False)
        except psycopg.errors.UniqueViolation:
            # A concurrent request claimed this client_order_id first; the row is
            # committed by the time the violation fires, so replay its order.
            with self._db.read() as conn:
                existing = TableRead.get_idempotency_order_id(conn, user.api_key, coid)
                return self._build_replay_response(conn, existing)
```

Confirm `TableRead` and `TableWrite` are imported in `order_service.py` (they are
used elsewhere in the file; add the imports if not).

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/onchain/test_idempotency.py -v`
Expected: both PASS (anvil running).

- [ ] **Step 8: Run the broader order suites for regressions**

Run: `pytest tests/onchain/test_order_cancel.py tests/onchain/test_data_orders.py tests/services/test_order_crossing.py tests/test_order_response.py -v`
Expected: all PASS (the normal path is behavior-preserved via `_fill_amounts`).

- [ ] **Step 9: Commit**

```bash
git add agentpit/services/order_service.py tests/onchain/test_idempotency.py
git commit -m "feat(orders): idempotent place_order via client_order_id claim + replay"
```

---

## Task 6: Config + purge idempotency keys in the cleanup loop

**Files:**
- Modify: `agentpit/config.py:75-80` (new retention field)
- Modify: `agentpit/api/app.py:250-255` (`_run_order_cleanup`)
- Test: `tests/db/test_idempotency.py`

- [ ] **Step 1: Write the failing test** (append to `tests/db/test_idempotency.py`)

```python
def test_run_order_cleanup_purges_idempotency_keys():
    import time as _time

    from agentpit.api.app import _run_order_cleanup

    db = DbSession(Settings().database_url)
    settings = Settings()
    now = int(_time.time())
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="stale", order_id="0x1",
            created_at=now - settings.idempotency_key_retention_seconds - 10,
        )
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="fresh", order_id="0x2",
            created_at=now,
        )
    _run_order_cleanup(db, settings)
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k", "stale") is None
        assert TableRead.get_idempotency_order_id(conn, "k", "fresh") == "0x2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_idempotency.py::test_run_order_cleanup_purges_idempotency_keys -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'idempotency_key_retention_seconds'`.

- [ ] **Step 3: Add the config field** to `agentpit/config.py` (right after `order_cancelled_retention_seconds`)

```python
    order_cancelled_retention_seconds: int = Field(
        default=600, validation_alias="AGENTPIT_ORDER_CANCELLED_RETENTION_SECONDS"
    )
    idempotency_key_retention_seconds: int = Field(
        default=86400, validation_alias="AGENTPIT_IDEMPOTENCY_KEY_RETENTION_SECONDS"
    )
```

- [ ] **Step 4: Purge keys in `_run_order_cleanup`** in `agentpit/api/app.py`

```python
def _run_order_cleanup(db: DbSession, settings: Settings) -> int:
    now = int(time.time())
    with db.write() as conn:
        purged = TableWrite.purge_cancelled_orders(
            conn, now - settings.order_cancelled_retention_seconds
        )
        TableWrite.purge_idempotency_keys(
            conn, now - settings.idempotency_key_retention_seconds
        )
    return purged
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/db/test_idempotency.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agentpit/config.py agentpit/api/app.py tests/db/test_idempotency.py
git commit -m "feat(orders): TTL-purge idempotency keys in the order-cleanup loop"
```

---

## Final verification

- [ ] **Run the full affected suites**

Run: `pytest tests/api/test_auth.py tests/test_place_order_request.py tests/db/test_idempotency.py tests/onchain/test_idempotency.py tests/onchain/test_order_cancel.py -v`
Expected: all PASS (onchain require anvil).

- [ ] **Sanity-check the wire**: register a user, grab `api_key`, place an order twice with the same `client_order_id` using only `X-API-Key`, confirm one order.
