# SQLite → Postgres migration — design spec

> Phase 5a (foundation) for the Liquidity Engine. Feeds a `writing-plans` plan, executed `subagent-driven`.

## 1. Context & goal

agentpit's data layer is a **single `sqlite3` connection behind one global mutex** (`agentpit/db/session.py`). Every read *and* write serializes through that one lock — see the comment in `DbSession` and the `tests/db/test_session_concurrency.py` regression. That is the hard concurrency ceiling.

The upcoming **in-process Liquidity Engine** (≈100 always-active house accounts, ~10 order-ops/sec/market across many markets) plus a production target means we need **real concurrent writers**. Move the persistence layer from SQLite to **PostgreSQL** with a **connection pool**, removing the global mutex.

**Scope:** swap the DB engine. Keep the existing **raw-SQL, no-ORM** style (the `TableRead`/`TableWrite` static-method idiom over a connection). This is an engine swap, not a re-architecture.

## 2. Non-goals / deferred

- **No ORM / query builder** (SQLAlchemy etc.). The codebase is deliberately raw SQL; keep it.
- **No async rewrite.** The service layer is sync; use **psycopg 3 in sync mode**. (asyncpg would force async through every service — out of scope.)
- **No data migration / ETL.** agentpit's DB is **ephemeral simulation state**: markets are re-synced from Polymarket on startup (`_polymarket_sync_loop` in `app.py`), users are faucet-funded, orders/trades/snapshots are sim data. Cutover = point at a fresh Postgres, `create_all_tables`, let the sync loop repopulate. (If any real data must be preserved later, ETL is a separate task.)
- **No Alembic** for now — keep the existing idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration style (Postgres supports both). Alembic can come later.

## 3. Decisions (confirm the ★ ones on review)

- **Driver:** **psycopg 3** (`psycopg[binary]`) + **`psycopg_pool.ConnectionPool`** (sync). *(Confirmed 2026-06-08.)* Rejected **SQLAlchemy** (the codebase is ~117 deliberate raw-SQL queries; an ORM/Core rewrite adds complexity without simplifying simple queries) and **asyncpg** (would force async through every sync route/service for no extra write-concurrency over a sync pool). Raw psycopg 3 is the minimal change that delivers concurrency.
- **Row access:** ★ standardize on **`dict_row`** for all pooled connections; convert the few positional-unpacking helpers (`_row_to_market`, `_row_to_user`, `_row_to_event`) to read by column name. (They already SELECT a fixed column list, so it's mechanical.) This gives one mental model (`row["COL"]`) and drops all `conn.row_factory = sqlite3.Row` juggling.
- **Param style:** `?` → `%s` (qmark → psycopg positional). Dynamic IN-lists `",".join("?"*n)` → `",".join(["%s"]*n)`. Watch literal `%` in any SQL string that also has `%s` params → double to `%%` (the current LIKE `%` lives in the *param value*, not the SQL literal, so it's mostly safe — verify per query).
- **Migrations:** keep idempotent. `CREATE TABLE IF NOT EXISTS` stays; `PRAGMA table_info`-based column adds → `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
- **Config:** `Settings.db_path` (default `:memory:`) → ★ **`database_url`** DSN (`AGENTPIT_DATABASE_URL`, e.g. `postgresql://agentpit:agentpit@localhost:5432/agentpit`).
- **Test DB:** tests run against a **real Postgres** *(confirmed)* — the suite already hard-requires anvil, so a required local Postgres is consistent and catches PG-only bugs. Per-test isolation via **`TRUNCATE` of all tables** in the autouse fixture against one session-scoped test database. (See §7.)
- **Local dev/test infra:** ★ **native Postgres via Homebrew is the primary path** (`brew install postgresql@16` + `brew services start postgresql@16`) — the user's Mac has no Docker daemon, and a native dev DB needs none. Also ship a `docker-compose.yml` (`postgres:16`) for CI / anyone running OrbStack or colima. The DSN is configurable so either works; nothing hard-depends on Docker.
- **Cutover shape:** ★ the conversion is **atomic for the DB layer** — you can't run SQLite SQL against Postgres, so schema + `DbSession` + every query must flip together. Done on a branch; the full suite is the gate. (Not incrementally shippable the way the API phases were.)

## 4. `DbSession` rework (the core)

Replace the single-connection-+-mutex with a pool:

```python
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

class DbSession:
    def __init__(self, dsn: str, *, min_size=2, max_size=16):
        self._pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
        with self._pool.connection() as conn:
            TableCreate.create_all_tables(conn)   # idempotent schema bootstrap

    @contextmanager
    def read(self):
        with self._pool.connection() as conn:     # checked out per call
            yield conn                             # psycopg autocommits/rolls back the txn on exit

    @contextmanager
    def write(self):
        with self._pool.connection() as conn:
            yield conn                             # commit on clean exit, rollback on exception

    def close(self):
        self._pool.close()
```

- **No global mutex** — the pool hands each thread its own connection (the entire point). Delete `self._lock`.
- `min/max_size` configurable (the engine wants headroom; default max 16, tune later).
- `read()` and `write()` both just check out a connection; psycopg's connection context manager handles commit/rollback. (If a read-only guarantee matters, `read()` can set the txn read-only — optional.)
- Keep the `read()`/`write()` API so call sites (`with self._db.read() as conn: conn.execute(...)`) are unchanged. psycopg `Connection` supports `.execute()` and `.cursor()`.

## 5. Schema translation (`table_create.py`) — incl. the BIGINT audit

Rewrite each `CREATE TABLE` in Postgres dialect. Type map:

| SQLite | Postgres | Notes |
|---|---|---|
| `TEXT` | `TEXT` | unchanged (token ids, condition ids, hashes, JSON blobs stay TEXT) |
| `INTEGER` (small flags/indexes) | `INTEGER` | only where the value is provably < 2³¹ (e.g. `BUCKET_INDEX`, `OUTCOME`/`RESOLVED_OUTCOME` index, `IS_BOT`, `POST_ONLY`, `NONCE`, `SIGNATURE_TYPE`) |
| `INTEGER` (money / amounts / unix-times) | **`BIGINT`** | ★ **SQLite INTEGER is 64-bit; Postgres `INTEGER` is only 32-bit.** These overflow 2³¹ and MUST be BIGINT |
| `INTEGER PRIMARY KEY [AUTOINCREMENT]` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` | `markets.MARKET_ID`, `events.EVENT_ID`, `transactions.TRANSACTION_ID`, `snapshots.SNAPSHOT_ID` |
| `DATETIME DEFAULT CURRENT_TIMESTAMP` | `timestamptz DEFAULT now()` | `transactions.TIMESTAMP` |

**BIGINT columns (explicit list — audit during implementation):**
- `orders`: `PRICE, MAKER_AMOUNT, TAKER_AMOUNT, REMAINING_AMOUNT, EXPIRATION, FEE_RATE_BPS, CREATED_AT`
- `trades`: `PRICE, TRADE_SIZE, REMAINING_SIZE, MATCH_TIME, FEE_RATE_BPS`
- `markets`: `START_DATE, END_DATE, POLYMARKET_ID`
- `snapshots`: `T, MID_MICRO_USD` (and `MARKET_ID` FK)
- `users`: `ONBOARDED_AT, CREATED_AT`
- `transactions`: `MARKET_ID` (FK) — and `TIMESTAMP` → timestamptz (above)

**Special — `orders.SALT`:** ★ it holds `secrets.randbits(256)` (a **256-bit** value, stored via `str(order.salt)`). That overflows **even BIGINT**. Make `SALT` **`NUMERIC(78)`** or **`TEXT`** (it's read back from `ORDER_JSON` as `int(...)`, and the column itself isn't used in arithmetic — `TEXT` is simplest and safe).

**`strftime('%s', TIMESTAMP)`** (activity / `account_service`) → `EXTRACT(EPOCH FROM TIMESTAMP)::bigint`.

## 6. Query / idiom conversion (the bulk)

~117 `.execute`, ~60 placeholder lines, across `table_read.py`, `table_write.py`, and raw-SQL in `order_service.py`, `account_service.py`, `snapshot_service.py`, `polymarket_sync.py`, `resolve.py`, `api/routes/users.py`. Per file:

- `?` → `%s` (incl. dynamic IN-list joins).
- `conn.row_factory = sqlite3.Row` + name access → rely on the pool's `dict_row` (remove the per-call `row_factory =` lines).
- positional `row[0]` unpacking (`_row_to_market`/`_row_to_user`/`_row_to_event`) → dict access by the known column names.
- `lastrowid` (1 use) → `INSERT ... RETURNING <id>` then `.fetchone()`.
- `strftime('%s', …)` → `EXTRACT(EPOCH FROM …)::bigint`.
- `LIKE ? ESCAPE '\'` → keep (Postgres supports `ESCAPE`); the wildcard lives in the param.
- `INSERT OR IGNORE` / `INSERT OR REPLACE` if any → `INSERT ... ON CONFLICT DO NOTHING/UPDATE` (grep to confirm; the codebase mostly does explicit existence checks).
- Booleans: `IS_BOT`/`POST_ONLY` kept as small INTEGER (code reads `bool(x)`) — no schema-bool change needed.

## 7. Test strategy

`tests/conftest.py` currently gives each test a fresh `:memory:` `DbSession` via an autouse fixture; 13 `:memory:` uses across the suite; `tests/db/test_session_concurrency.py` is a lock regression.

Plan:
- **Session-scoped test Postgres.** conftest connects to a dedicated test database (DSN from `AGENTPIT_TEST_DATABASE_URL`, default a local `agentpit_test`). Create the schema once.
- **Per-test isolation:** the autouse fixture **`TRUNCATE`s every table** (one statement, `TRUNCATE t1, t2, ... RESTART IDENTITY CASCADE`) before/after each test — fast and fully isolating. Replaces "fresh `:memory:` DbSession" semantics.
- Tests that construct their own `DbSession(":memory:")` (e.g. `tests/db/`, some `tests/onchain/` and `tests/polymarket/`) → construct `DbSession(test_dsn)` instead (a tiny helper `fresh_test_db()` in a shared place).
- **`test_session_concurrency.py`:** its premise (one shared connection isn't thread-safe) no longer holds. **Repurpose** it to assert the *pool* survives many concurrent reader+writer threads without corruption/deadlock (a genuine concurrency smoke test for the new design).
- Dev/test infra: **primary = native Homebrew Postgres** (`brew install postgresql@16`; `brew services start postgresql@16`; `createdb agentpit` + `createdb agentpit_test`) — works on the Mac with no Docker daemon. **Also** ship `docker-compose.yml` (`postgres:16`) for CI / OrbStack / colima users. The suite needs a Postgres reachable at the test DSN, like it already needs anvil.

## 8. Config & app wiring

- `Settings.db_path` → `database_url: str` (`AGENTPIT_DATABASE_URL`). Remove `:memory:` default; default to the local dev DSN.
- `app.py:129` `DbSession(settings.db_path)` → `DbSession(settings.database_url)`. The singleton-per-app stays (now wrapping a pool).
- Pool lifecycle: open at app startup, `close()` on shutdown (the existing lifespan/`close()` hooks).

## 9. Phasing (one coordinated migration, reviewed as a whole)

Because the DB layer is atomic (no half-SQLite/half-PG), this is **one branch / one coordinated change**, broken into ordered sub-steps for the implementer but gated by the full suite at the end (not independently shippable like the API phases):

1. Deps + config + docker-compose/run-script + test DSN plumbing.
2. `table_create.py` → Postgres dialect (types, BIGINT/SALT audit, IDENTITY, timestamptz, `ADD COLUMN IF NOT EXISTS`).
3. `DbSession` → pool (`§4`).
4. `table_read.py` queries (`§6`).
5. `table_write.py` queries.
6. Raw-SQL services (`order_service`, `account_service`, `snapshot_service`, `polymarket_sync`, `resolve`, `users` route).
7. `conftest.py` + test-DB isolation; repurpose the concurrency test.
8. Full suite green (incl. on-chain) + a pool-concurrency check.

## 10. Risks

- **INTEGER overflow** (the #1 correctness trap) — mitigated by the §5 BIGINT/SALT audit; add a test that places an order with large amounts and round-trips it.
- **Transaction semantics drift:** SQLite `with conn:` ≈ psycopg connection-context commit/rollback, but verify the `write()` paths that span multiple statements (e.g. `place_order` insert+match+settle) commit atomically and roll back on settlement failure as today.
- **Row-factory mix-ups** (positional vs dict) — caught by tests, but audit the 3 `_row_to_*` helpers.
- **`%` in SQL literals** alongside `%s` — grep for it.
- **Test-suite blast radius:** every test now needs Postgres; the conftest change is load-bearing — land it early and run the full suite often.

## 11. Acceptance criteria

- Full pytest suite green against Postgres (on-chain tests included).
- No `sqlite3` import remains in `agentpit/` (only psycopg).
- The global `DbSession` mutex is gone; the repurposed concurrency test proves the pool handles parallel read+write threads.
- A large-amount order round-trips (BIGINT/SALT proof).
- App boots, syncs markets, and serves the migrated API against a fresh Postgres.
