# SQLite → Postgres migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace agentpit's SQLite data layer with PostgreSQL + a psycopg3 connection pool, removing the single-connection global mutex (the concurrency ceiling) — keeping the existing raw-SQL `TableRead`/`TableWrite` idiom.

**Spec:** `docs/superpowers/specs/2026-06-08-sqlite-to-postgres-migration-design.md` (read it — it has the decisions + the full BIGINT audit).

**Architecture:** psycopg 3 (sync) + `psycopg_pool.ConnectionPool`; uniform `dict_row`; idempotent `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`; ephemeral DB (no data migration); tests against a real local Postgres.

**Atomic note:** the DB layer can't be half-migrated, so tasks 1–5 are verified by *compile/import + grep* (no `?`/`sqlite3` left), and **Task 6 is the behavioral gate** (full pytest suite green on Postgres). Run Python via `.venv/bin/python`. On-chain tests still need the forked anvil (`scripts/run_node.sh` + `scripts/deploy_exchange.sh`).

---

## Task 1: Dependencies, config, local Postgres

**Files:** `requirements.txt`, `agentpit/config.py`, `docker-compose.yml` (create), `scripts/run_postgres.sh` (create), `README`/docs note.

- [ ] **Step 1: Install the driver**

Append to `requirements.txt`:
```
psycopg[binary]>=3.2
psycopg_pool>=3.2
```
Run: `.venv/bin/pip install 'psycopg[binary]>=3.2' 'psycopg_pool>=3.2'`

- [ ] **Step 2: Local Postgres (native, no Docker daemon)**

```bash
brew install postgresql@16
brew services start postgresql@16
createdb agentpit
createdb agentpit_test
```
Verify: `.venv/bin/python -c "import psycopg; psycopg.connect('postgresql:///agentpit_test').close(); print('pg ok')"`

- [ ] **Step 3: Config — `db_path` → `database_url`**

In `agentpit/config.py`, replace the `db_path` field:
```python
    database_url: str = Field(
        default="postgresql:///agentpit",
        validation_alias="AGENTPIT_DATABASE_URL",
    )
```
(Grep `settings.db_path` / `db_path` across `agentpit/` and update call sites — there is one real one at `app.py:129`, handled in Task 3.)

- [ ] **Step 4: docker-compose for CI/OrbStack users (optional path)**

Create `docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: agentpit
      POSTGRES_PASSWORD: agentpit
      POSTGRES_DB: agentpit
    ports: ["5432:5432"]
    volumes: ["agentpit_pg:/var/lib/postgresql/data"]
volumes:
  agentpit_pg:
```
Create `scripts/run_postgres.sh` (mirrors `run_node.sh`): brings up native or compose Postgres + `createdb agentpit agentpit_test` idempotently. Document both paths in the README's dev-setup section.

- [ ] **Step 5: Commit**
```bash
git add requirements.txt agentpit/config.py docker-compose.yml scripts/run_postgres.sh
git commit -m "build(db): add psycopg3+pool, database_url config, local Postgres setup"
```

---

## Task 2: Postgres schema (`table_create.py`)

**Files:** `agentpit/db/table_create.py`. **Test:** `tests/db/test_pg_schema.py` (create).

Rewrite every `CREATE TABLE` + migration in Postgres dialect per the spec §5 audit. Rules:
- money/amount/unix-time `INTEGER` → **`BIGINT`** (spec lists every column); small index/flag `INTEGER` stays `INTEGER`.
- `orders.SALT` → **`TEXT`** (256-bit).
- `INTEGER PRIMARY KEY [AUTOINCREMENT]` → `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`.
- `DATETIME DEFAULT CURRENT_TIMESTAMP` → `timestamptz DEFAULT now()`.
- `PRAGMA table_info(...)`-based column adds → `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`.
- keep `CREATE TABLE IF NOT EXISTS`, `UNIQUE`, `NOT NULL`, `DEFAULT`.

- [ ] **Step 1: Write the failing test**

`tests/db/test_pg_schema.py`:
```python
"""create_all_tables builds the Postgres schema; BIGINT/SALT survive large values."""
import psycopg
import pytest
from agentpit.db.table_create import TableCreate

DSN = "postgresql:///agentpit_test"


@pytest.fixture()
def conn():
    c = psycopg.connect(DSN, autocommit=True)
    # clean slate
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    yield c
    c.close()


def test_creates_all_tables(conn):
    TableCreate.create_all_tables(conn)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    names = {r[0] for r in rows}
    for t in ("users", "markets", "orders", "trades", "events", "transactions"):
        assert t in names


def test_bigint_amounts_round_trip(conn):
    TableCreate.create_all_tables(conn)
    big = 9_000_000_000_000          # > 2^31, would overflow INTEGER
    salt = str(2**255)               # 256-bit
    conn.execute(
        "INSERT INTO orders (ORDER_ID, MAKER_AMOUNT, TAKER_AMOUNT, REMAINING_AMOUNT, "
        "PRICE, SALT, CREATED_AT, STATUS) VALUES (%s,%s,%s,%s,%s,%s,%s,'live')",
        ("o1", big, big, big, 600000, salt, 1700000000),
    )
    row = conn.execute(
        "SELECT MAKER_AMOUNT, SALT FROM orders WHERE ORDER_ID='o1'"
    ).fetchone()
    assert row[0] == big and row[1] == salt
```

- [ ] **Step 2: Run → fails** (`table_create` still SQLite). `.venv/bin/python -m pytest tests/db/test_pg_schema.py -v`

- [ ] **Step 3: Rewrite `table_create.py`** per the rules above. (`create_all_tables(conn)` now takes a psycopg connection; `db.execute(...)` works the same.)

- [ ] **Step 4: Run → passes** (2 passed). This proves the schema + the BIGINT/SALT fix against real Postgres.

- [ ] **Step 5: Commit** `feat(db): Postgres schema (BIGINT amounts, SALT TEXT, IDENTITY, timestamptz)`

---

## Task 3: `DbSession` → connection pool

**Files:** `agentpit/db/session.py`, `agentpit/api/app.py`.

- [ ] **Step 1: Rewrite `session.py`** to the pool (spec §4): `ConnectionPool(dsn, kwargs={"row_factory": dict_row, "autocommit": False}, open=True)`; `read()`/`write()` check out `self._pool.connection()`; **delete the `threading.Lock`**; bootstrap `create_all_tables` once at init; `close()` closes the pool.

- [ ] **Step 2: Wire `app.py`** — `DbSession(settings.db_path)` → `DbSession(settings.database_url)` (line ~129). Confirm pool `close()` is called on app shutdown (existing lifespan/close hook).

- [ ] **Step 3: Verify import + a live read/write**
```bash
.venv/bin/python -c "
from agentpit.db.session import DbSession
db = DbSession('postgresql:///agentpit_test')
with db.write() as c: c.execute(\"INSERT INTO personalities (PERSONALITY_ID,PERSONALITY_TITLE,PERSONALITY_SPEC) VALUES ('p','t','s') ON CONFLICT DO NOTHING\")
with db.read() as c: print('rows', c.execute('SELECT count(*) FROM personalities').fetchone())
db.close(); print('pool ok')"
```
Expected: prints a count + `pool ok`.

- [ ] **Step 4: Commit** `feat(db): DbSession uses a psycopg pool (drop the global mutex)`

---

## Task 4: Convert `table_read.py` + `table_write.py`

**Files:** `agentpit/db/table_read.py`, `agentpit/db/table_write.py`.

Mechanical per spec §6: `?`→`%s` (incl. dynamic IN-joins `",".join(["%s"]*n)`); drop `conn.row_factory = sqlite3.Row` (pool gives `dict_row`); convert the positional unpackers `_row_to_market`/`_row_to_user`/`_row_to_event` to **dict access by column name** (they SELECT a fixed `_*_COLS` list — map names → values); `lastrowid` → `INSERT ... RETURNING <id>` + `.fetchone()`; remove `import sqlite3` if now unused (keep type hints generic, e.g. `conn` untyped or `psycopg.Connection`).

- [ ] **Step 1:** Convert `table_read.py`. Verify: `.venv/bin/python -c "import agentpit.db.table_read"` and `grep -nE "\?|sqlite3\.Row|row_factory" agentpit/db/table_read.py` → no SQLite placeholders/Row left.
- [ ] **Step 2:** Convert `table_write.py`. Same verification.
- [ ] **Step 3: Commit** `feat(db): convert table_read/table_write queries to psycopg (%s, dict rows)`

---

## Task 5: Convert raw-SQL services

**Files:** `agentpit/services/order_service.py`, `agentpit/services/account_service.py`, `agentpit/services/snapshot_service.py`, `agentpit/polymarket/polymarket_sync.py`, `agentpit/polymarket/resolve.py`, `agentpit/api/routes/users.py`.

Same conversion patterns. Extra: `strftime('%s', TIMESTAMP)` → `EXTRACT(EPOCH FROM TIMESTAMP)::bigint` (in `account_service` activity); audit each multi-statement `write()` (esp. `order_service.place_order` insert→match→settle) still commits atomically / rolls back on settlement failure as today (psycopg connection-context handles it — just verify no stray autocommit).

- [ ] **Step 1:** Convert all six files. Verify each imports and has no `?`/`sqlite3.Row`/`row_factory`/`strftime` left:
```bash
for f in agentpit/services/order_service.py agentpit/services/account_service.py agentpit/services/snapshot_service.py agentpit/polymarket/polymarket_sync.py agentpit/polymarket/resolve.py agentpit/api/routes/users.py; do
  .venv/bin/python -c "import importlib,sys; importlib.import_module('${f%.py}'.replace('/','.'))" && echo "import ok: $f"
done
grep -rnE "= \?|VALUES.*\?|sqlite3\.Row|strftime\(" agentpit/services agentpit/polymarket agentpit/api/routes/users.py | grep -v __pycache__ || echo "  (clean)"
```
- [ ] **Step 2: Confirm no sqlite3 anywhere in app code:** `grep -rn "sqlite3" agentpit/ | grep -v __pycache__` → empty.
- [ ] **Step 3: Commit** `feat(db): convert raw-SQL services to psycopg`

---

## Task 6: Test infra + full-suite gate

**Files:** `tests/conftest.py`, `tests/db/test_session_concurrency.py`, and any `DbSession(":memory:")` call sites (`tests/db/`, `tests/onchain/`, `tests/polymarket/`).

- [ ] **Step 1: conftest → Postgres** — point at `AGENTPIT_TEST_DATABASE_URL` (default `postgresql:///agentpit_test`). Set it before app import. The autouse fixture: instead of a fresh `:memory:` `DbSession`, give a session-scoped `DbSession(test_dsn)` and **`TRUNCATE` every table `RESTART IDENTITY CASCADE`** before each test. Add a shared `fresh_test_db()` helper returning `DbSession(test_dsn)` for tests that build their own.

- [ ] **Step 2: Migrate `:memory:` sites** — replace `DbSession(":memory:")` with `fresh_test_db()` (or an in-test truncate) across `tests/`. Grep `:memory:` → none left.

- [ ] **Step 3: Repurpose `test_session_concurrency.py`** — its old premise (one shared connection) is gone. Rewrite it to spawn many threads doing concurrent reads+writes through the pool and assert no errors / consistent results (a real pool concurrency check).

- [ ] **Step 4: THE GATE — full suite on Postgres**

Run (anvil must be up): `.venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all pass (the ~256 baseline, now on Postgres). Fix conversions until green.

- [ ] **Step 5: Final checks**
```bash
grep -rn "sqlite3\|:memory:\|db_path" agentpit/ tests/ | grep -v __pycache__   # expect empty
```
- [ ] **Step 6: Commit** `test(db): run suite against Postgres (per-test truncate); pool concurrency test`
- [ ] **Step 7:** Dispatch the final whole-phase review, then `superpowers:finishing-a-development-branch`.

---

## Self-review checklist (run before the gate)
- Every BIGINT column from the spec §5 list is BIGINT; `SALT` is TEXT. (The Task-2 round-trip test proves the critical ones.)
- No `sqlite3` import, no `?` placeholder, no `:memory:`, no `db_path` left in `agentpit/`.
- `DbSession` has no `threading.Lock`.
- `place_order` (insert→match→settle) commits atomically and still rolls back trades on settlement failure.
- Dynamic IN-clauses use `%s`, not `?`.
