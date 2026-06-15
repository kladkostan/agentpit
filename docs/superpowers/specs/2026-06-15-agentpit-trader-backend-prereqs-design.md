# agentpit backend prerequisites for agentpit-trader — design spec

**Date:** 2026-06-15
**Status:** approved (pending written-spec review)

## 1. Overview

Two additive, backward-compatible backend changes to agentpit so an autonomous
trading bot (the future `agentpit-trader` OpenClaw plugin) can run a 24/7 trading
loop against the agentpit sandbox without operational footguns:

1. **Long-lived `X-API-Key` authentication** — so the bot doesn't have to store
   an email/password and re-login every time the 24h JWT expires.
2. **Idempotent `POST /order`** — so a network retry after a timeout can't
   double-place an order (real-money risk in live mode, accounting noise in
   sandbox).

Both are additive: existing callers (the liquidity mirror engine, the JWT-based
UI) are unaffected. Neither is a hard blocker for the bot (both have adapter-side
workarounds), but closing them on the backend makes the bot robust by
construction rather than by fragile client-side compensation.

Market data (orderbook, trade tape, price history, market metadata) is **not** in
scope: the bot reads that from the real Polymarket public APIs using the real
Polymarket IDs agentpit already stores per market
(`polymarket_condition_id`, `polymarket_yes_token_id`, `polymarket_no_token_id`).

## 2. Scope

**In scope**
- Expose the existing per-user `api_key` and accept it as a long-lived credential
  via an `X-API-Key` header.
- Add an optional `client_order_id` to `POST /order` with race-safe server-side
  dedup and a TTL.

**Out of scope (YAGNI)**
- api_key rotation / revocation, `/auth/refresh`, a named-token table.
- Idempotency for cancels (already effectively idempotent: re-cancelling returns
  `not_canceled` as a no-op).
- A public market-wide trade tape and a server-side `active` market filter —
  both covered by reading from Polymarket.

## 3. Current state (verified)

- **Auth** is JWT-only. `register`/`login` return `AuthResponse{access_token,
  token_type:"bearer", user: UserPublic}`; the per-user `api_key` (a
  `uuid.uuid4()` generated at `TableWrite.create_user`,
  `agentpit/db/table_write.py:34`) is **discarded, never returned to the client**
  (`agentpit/services/auth_service.py:45`). The JWT decodes to a user in
  `make_current_user_dep` (`agentpit/auth/dependencies.py:36`) and expires after
  `jwt_expires_seconds` (default 24h, `agentpit/config.py:123`).
- `TableRead.get_user_by_api_key` **already exists**
  (`agentpit/db/table_read.py:202`).
- `UserPublic` (`agentpit/datastructures/auth_response.py:4`) is returned **only
  in self contexts** — `register`/`login` responses and `GET/PATCH /me`. No
  endpoint returns another user's `UserPublic`.
- **Orders** have no idempotency. `place_order` builds an `OrderData` with a
  random `salt=secrets.randbits(256)` (`agentpit/services/order_service.py:111`)
  and derives `order_id` from the order content, so two identical logical orders
  get different ids; there is no `client_order_id` concept anywhere. The order
  insert + matching run in one write transaction; on-chain settlement happens
  after that transaction.
- A cleanup loop already runs: `_order_cleanup_loop` → `_run_order_cleanup` →
  `TableWrite.purge_cancelled_orders(db, before_ts)`
  (`agentpit/api/app.py:258`, `agentpit/db/table_write.py:649`), gated on
  `order_cleanup_interval_seconds` (`agentpit/config.py:75`).

## 4. Feature 1 — Long-lived `X-API-Key` auth

### 4.1 Accept the key (core)

Extend `make_current_user_dep` with a second credential branch using FastAPI's
`APIKeyHeader(name="X-API-Key", auto_error=False)`:

```python
def current_user(api_key, creds, db) -> User:
    if api_key:                                   # X-API-Key branch
        with db.read() as conn:
            user = TableRead.get_user_by_api_key(conn, api_key)
        if user is None:
            raise _unauth("invalid api key")
        return user
    # fall back to existing JWT branch (unchanged)
    if creds is None or not creds.credentials:
        raise _unauth("missing credentials")
    ...decode JWT, look up by sub, return user...
```

- Precedence: `X-API-Key` is checked first; absent → JWT path. Neither present →
  401. Invalid key → 401. The JWT path is byte-for-byte unchanged.
- No change to the `CurrentUserDep` type or any route — every authenticated route
  transparently accepts either credential.

### 4.2 Expose the key

Add `api_key: str` to `UserPublic`. The bot calls `register`/`login` once (or
`GET /me`), reads `api_key` from the response, then sends `X-API-Key` on every
subsequent request. Safe because `UserPublic` is only ever the authenticated
self.

### 4.3 Security trade-off (explicit)

`api_key` becomes a bare, non-expiring, non-rotatable secret stored in plaintext
(it also serves as the internal partition key for orders/trades, so rotation
would mean rewriting those rows — hence out of scope). This is **acceptable for
the sandbox**: a local-network paper-trading rig on anvil with faucet USDC. If
agentpit ever serves real funds or untrusted multi-tenant traffic, replace this
with a hashed, revocable token table — called out here as a known limit, not an
oversight.

## 5. Feature 2 — Idempotent `POST /order`

### 5.1 Request

Add an **optional** field to `PlaceOrderRequest`:

```python
client_order_id: str | None = None
```

Absent → current behavior (no dedup), preserving backward compatibility with the
mirror engine and any existing caller. Present → dedup applies.

### 5.2 Storage

A dedicated table (not a column on the hot, partial-indexed `orders` table):

```sql
CREATE TABLE IF NOT EXISTS idempotency_keys (
    API_KEY         TEXT   NOT NULL,
    CLIENT_ORDER_ID TEXT   NOT NULL,
    ORDER_ID        TEXT   NOT NULL,
    CREATED_AT      BIGINT NOT NULL,           -- unix seconds
    PRIMARY KEY (API_KEY, CLIENT_ORDER_ID)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_created_at
    ON idempotency_keys(CREATED_AT);
```

The composite primary key is the race-safety primitive; the `CREATED_AT` index
serves the TTL purge. Keys are namespaced per `API_KEY`, so two users can reuse
the same `client_order_id` independently.

### 5.3 Race-safe claim flow

In `place_order`, when `client_order_id` is set:

```python
# Fast path: a prior attempt already claimed this key -> replay its order.
existing = TableRead.get_idempotency_order_id(conn, api_key, coid)
if existing is not None:
    return self._build_response_for(conn, existing)

try:
    with self._db.write() as conn:
        TableWrite.claim_idempotency_key(conn, api_key, coid, order_id)  # may raise
        self._insert_order(conn, ...)            # same transaction
        matches = self._match(conn, taker_row)
except psycopg.errors.UniqueViolation:
    # Lost a concurrent race: the other request claimed it first.
    with self._db.read() as conn:
        existing = TableRead.get_idempotency_order_id(conn, api_key, coid)
    return self._build_response_for(conn, existing)
```

Invariants:
- The idempotency row and the order row are inserted in the **same transaction**,
  so the key never points to a non-existent order (a failed insert rolls back
  both).
- The `UniqueViolation` catch handles the genuine concurrent-duplicate race; the
  read fast-path handles the common sequential-retry case cheaply.
- Settlement still happens after the transaction. A retry that hits the fast-path
  / race-catch returns the order's **current** state and does **not** re-place or
  re-settle.

### 5.4 Replay response

On a duplicate, reconstruct `OrderResponse` from the existing order row + its
trades (single source of truth = the order's actual state). The response-building
logic is currently inline at the tail of `place_order`; it will be extracted into
a small helper `_build_response_for(conn, order_id)` so both the normal path and
the replay path share it. We deliberately do **not** store a response blob — the
order's current state is both simpler and more useful for a bot reconciling.

### 5.5 Failure semantics

If the first attempt produced `success=False` (e.g. on-chain settlement failed),
the order row exists, so a retry with the same `client_order_id` replays that
failed response. To genuinely re-attempt, the caller must use a **new**
`client_order_id`. This is correct idempotency: the action was performed; its
outcome was failure.

### 5.6 TTL

Add `purge_idempotency_keys(db, before_ts)` and call it from the existing
`_run_order_cleanup` alongside `purge_cancelled_orders`. Retention is a new config
`idempotency_key_retention_seconds` (default `86400` = 24h). After expiry a key
may be reused (treated as new) — acceptable.

## 6. Files touched

| File | Change |
|---|---|
| `agentpit/auth/dependencies.py` | `X-API-Key` branch in `make_current_user_dep` |
| `agentpit/datastructures/auth_response.py` | `api_key` field on `UserPublic` |
| `agentpit/services/auth_service.py` | populate `api_key` in `_issue` |
| `agentpit/api/routes/users.py` | `/me` already returns `UserPublic` (no logic change; field flows through) |
| `agentpit/datastructures/place_order_request.py` | optional `client_order_id` |
| `agentpit/services/order_service.py` | claim flow in `place_order` |
| `agentpit/db/table_create.py` | `idempotency_keys` table + index |
| `agentpit/db/table_write.py` | `claim_idempotency_key`, `purge_idempotency_keys` |
| `agentpit/db/table_read.py` | `get_idempotency_order_id` |
| `agentpit/api/app.py` | call purge in `_run_order_cleanup` |
| `agentpit/config.py` | `idempotency_key_retention_seconds` |

## 7. Testing (TDD)

**Auth**
- `X-API-Key` with a valid key authenticates; response identity matches the user.
- Existing JWT bearer flow still authenticates unchanged.
- Invalid/unknown `X-API-Key` → 401; no credentials → 401.
- `api_key` is present in `register`/`login`/`GET /me` responses.

**Idempotency**
- Two sequential `POST /order` with the same `client_order_id` → identical
  `order_id`; exactly one order exists.
- Concurrent duplicates (two writers racing the unique constraint) → exactly one
  order; both callers get the same `order_id`.
- `client_order_id` absent → no dedup (legacy behavior; two orders).
- First attempt fails (`success=False`) → retry replays the failure.
- `purge_idempotency_keys` deletes rows older than retention and keeps newer ones.

## 8. Edge cases

- Same `client_order_id`, different users → independent (namespaced by `API_KEY`).
- Key reused after TTL purge → treated as a fresh order (documented, acceptable).
- Crash between transaction commit and on-chain settlement → matched trades exist
  in DB but unsettled; this is a pre-existing property of the two-phase
  match-then-settle design, unchanged by idempotency, and is reconciled by the
  bot via `/data/trades`.

## 9. Config additions

```python
idempotency_key_retention_seconds: float = Field(
    default=86400.0, validation_alias="IDEMPOTENCY_KEY_RETENTION_SECONDS"
)
```
