# Real Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank every account that has traded — our five personalities and anyone who followed the builder guide — on a board the Arena reads from the API instead of a stale static file.

**Architecture:** A timed pass values each traded account and writes a row into a new `account_snapshots` table, the same shape `price_snapshots` already uses for market mids. The board is assembled at the end of each pass and held in memory, the way `routes/events.py` caches its listing, so the Arena's four-second poll costs nothing. A per-account deployment identity makes a chain wipe an edge rather than a level, which is what the reverted reset got wrong.

**Tech Stack:** Python 3.13 / FastAPI / psycopg3 / pydantic; React 19 / TypeScript / Vite.

## Global Constraints

- apUSD is **6-decimal**. $100,000 = `100_000_000_000` raw. Every stored figure is a raw int.
- `AccountService.total_value(address)` returns `[{"user": address, "value": <float whole apUSD>}]`; raw conversion is `int(round(value * 10**6))`.
- **The email address is never exposed** — not in any payload, not as a name fallback, not derivable. There is a test asserting this against the response body.
- The board's default sort is **return**. Capital alone ranks whoever pressed the top-up button most.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` from the repo root. **NEVER source `.env`** — conftest setdefaults get defeated and live-sync tests hang. Currently **424 passed**; must end green.
- UI chain from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. Lint must stay at **0 errors** (3 pre-existing `react-refresh` warnings expected).
- Commit messages carry **no AI attribution trailer**. Stage files by name; never `git add -A`.

## File Structure

| file | responsibility |
|---|---|
| `agentpit/db/table_create.py` | `account_snapshots` table; `users.DEPLOYMENT_ID` column |
| `agentpit/db/table_read.py` | `get_deployment_id`, `list_traded_accounts`, `latest_account_snapshots` |
| `agentpit/db/table_write.py` | `set_deployment_id`, `insert_account_snapshot`, `prune_account_snapshots` |
| `agentpit/onchain/admin.py` | `deployment_id` property — the identity the wipe check compares |
| `agentpit/services/balance_service.py` | detect a changed deployment, reset before claiming |
| `agentpit/services/auth_service.py` | record the identity at registration |
| `agentpit/services/leaderboard_service.py` | **new** — the valuation pass and the ranking |
| `agentpit/api/routes/leaderboard.py` | **new** — `GET /leaderboard` and the in-memory board |
| `agentpit/api/app.py` | the timer |
| `ui/src/api/leaderboard.ts` | fetch and types |
| `ui/src/pages/AgentArenaPage.tsx` | render from the endpoint |

---

### Task 1: A chain wipe becomes an edge, not a level

**Files:**
- Modify: `agentpit/db/table_create.py` (the `additions` list in `_migrate_users_table`)
- Modify: `agentpit/db/table_read.py`, `agentpit/db/table_write.py`
- Modify: `agentpit/onchain/admin.py`
- Modify: `agentpit/services/balance_service.py`, `agentpit/services/auth_service.py`
- Modify: `tests/test_balance_topup.py`

**Interfaces:**
- Produces: `OnchainAdmin.deployment_id -> str`; `TableRead.get_deployment_id(db, user_id) -> str | None`; `TableWrite.set_deployment_id(db, user_id, deployment_id)`; `TableWrite.reset_deposits(db, user_id, deployment_id)`.

**Why this is not the reverted version.** The previous attempt detected a wipe by
zero native balance. Nothing on the top-up path refunds gas, so the condition
stayed true and the reset re-fired on every later top-up, discarding what it had
just recorded. A deployment identity changes exactly once per redeploy, and the
reset writes it, so the condition clears itself.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_balance_topup.py`:

```python
def test_deposits_reset_when_the_deployment_changes():
    """A redeploy means new contracts, so everything granted before it no
    longer exists on chain. The stored identity is what makes this an edge:
    the reset writes the new one, so it cannot fire twice for one wipe."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="redeploy@example.com", password_hash="x", handle=None
    )
    TableWrite.set_total_deposited(conn, user_id, 500_000_000_000)
    TableWrite.set_deployment_id(conn, user_id, "0xOLD")
    assert TableRead.get_deployment_id(conn, user_id) == "0xOLD"

    TableWrite.reset_deposits(conn, user_id, "0xNEW")

    assert TableRead.get_total_deposited(conn, user_id, 0) == 0
    assert TableRead.get_deployment_id(conn, user_id) == "0xNEW"
    conn.close()


def test_reset_is_idempotent_so_two_racing_callers_agree():
    """Both callers of a concurrent top-up may see the changed identity. The
    reset sets to zero rather than subtracting, so whichever order they land
    in, the row ends up the same and the claim that wins adds its mint once."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="race-reset@example.com", password_hash="x", handle=None
    )
    TableWrite.set_total_deposited(conn, user_id, 500_000_000_000)
    TableWrite.set_deployment_id(conn, user_id, "0xOLD")

    TableWrite.reset_deposits(conn, user_id, "0xNEW")
    TableWrite.reset_deposits(conn, user_id, "0xNEW")

    assert TableRead.get_total_deposited(conn, user_id, 0) == 0
    conn.close()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "deployment or racing"
```

Expected: `AttributeError: type object 'TableWrite' has no attribute 'set_deployment_id'`.

- [ ] **Step 3: Add the column**

In `agentpit/db/table_create.py`, append to the `additions` list in `_migrate_users_table`:

```python
            ("DEPLOYMENT_ID", "TEXT"),
```

- [ ] **Step 4: Add the accessors**

In `agentpit/db/table_read.py`, beside `get_total_deposited`:

```python
    @staticmethod
    def get_deployment_id(db: psycopg.Connection, user_id: str) -> str | None:
        """Which chain deployment this account's figures were recorded against.

        NULL means the row predates the column; the caller records the current
        identity without resetting, because it has no evidence a wipe happened.
        """
        row = db.execute(
            "SELECT DEPLOYMENT_ID FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        return row["DEPLOYMENT_ID"] if row else None
```

In `agentpit/db/table_write.py`:

```python
    @staticmethod
    def set_deployment_id(
        db: psycopg.Connection, user_id: str, deployment_id: str
    ) -> None:
        db.execute(
            "UPDATE users SET DEPLOYMENT_ID = %s WHERE USER_ID = %s",
            (deployment_id, user_id),
        )

    @staticmethod
    def reset_deposits(
        db: psycopg.Connection, user_id: str, deployment_id: str
    ) -> None:
        """Start the deposit ledger over against a new deployment.

        Sets to zero rather than adjusting by a delta, so two callers who both
        noticed the same wipe leave the row in the same state. Writing the new
        identity in the same statement is what stops it firing twice.
        """
        db.execute(
            "UPDATE users SET TOTAL_DEPOSITED = 0, DEPLOYMENT_ID = %s "
            "WHERE USER_ID = %s",
            (deployment_id, user_id),
        )
```

- [ ] **Step 5: Expose the identity from OnchainAdmin**

In `agentpit/onchain/admin.py`, add as a property on the class:

```python
    @property
    def deployment_id(self) -> str:
        """Identity of the chain deployment these contracts belong to.

        The CTF address: a redeploy always produces a new one, because the
        contracts themselves are new. Callers compare it against what they
        recorded to tell "the chain was replaced" from "nothing happened",
        without an RPC round-trip.
        """
        return self._client.deployment.ctf
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "deployment or racing"
```

Expected: 2 passed.

- [ ] **Step 7: Detect the change in top_up**

In `agentpit/services/balance_service.py`, inside `top_up`, replace the `KNOWN LIMITATION` comment block (it documented exactly this gap) with the check. Put it after the `minted == 0` early return and before the claim:

```python
        # A redeploy replaces the contracts, so everything granted against the
        # old ones is gone -- but the database survives and would carry the
        # figure forward, making `earned` read deeply negative. The stored
        # identity makes this an edge: the reset writes the new one, so it
        # fires exactly once per redeploy per account. (An earlier attempt used
        # a zero native balance, which is a level -- nothing here refunds gas,
        # so it stayed true and re-fired on every later top-up.)
        current_deployment = self._onchain.deployment_id
        with self._db.read() as conn:
            seen_deployment = TableRead.get_deployment_id(conn, user.user_id)
        if seen_deployment is None:
            # Predates the column: record it, but claim no knowledge of a wipe.
            with self._db.write() as conn:
                TableWrite.set_deployment_id(
                    conn, user.user_id, current_deployment
                )
        elif seen_deployment != current_deployment:
            with self._db.write() as conn:
                TableWrite.reset_deposits(
                    conn, user.user_id, current_deployment
                )
```

- [ ] **Step 8: Record the identity at registration**

In `agentpit/services/auth_service.py`, the registration path already writes `TOTAL_DEPOSITED` from the chain in its own transaction. Add the identity to that same write, so a new account starts with both:

```python
            granted = self._onchain.usd_balance(acct.address)
            with self._db.write() as conn:
                TableWrite.set_total_deposited(conn, user_id, granted)
                TableWrite.set_deployment_id(
                    conn, user_id, self._onchain.deployment_id
                )
```

Match the variable names the surrounding block already uses.

- [ ] **Step 9: Update the launch plan**

In `docs/launch-plan.md`, the leaderboard section carries a precondition beginning **"Precondition: do not ship this while `AGENTPIT_SIMULATED_CHAIN` is true."** Replace that whole paragraph with:

```markdown
**That precondition is lifted.** `TOTAL_DEPOSITED` used to be wrong after a
chain wipe, because the database outlives a disposable anvil. It is now keyed
to the deployment: every redeploy writes new contract addresses, the account
records which one its figures belong to, and a mismatch resets the ledger
exactly once. No native-balance guess, no RPC, and nothing that can fire twice.
```

- [ ] **Step 10: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 11: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py agentpit/db/table_write.py \
        agentpit/onchain/admin.py agentpit/services/balance_service.py \
        agentpit/services/auth_service.py tests/test_balance_topup.py docs/launch-plan.md
git commit -m "feat(balance): key the deposit ledger to the chain deployment

A redeploy replaces the contracts, so everything granted against the old ones
is gone -- but the database survives and carried the figure forward, which
would have made every reonboarded account read deeply negative on the
leaderboard. The account now records which deployment its figures belong to
and a mismatch resets the ledger exactly once.

This is the fix that was reverted from top_up in its earlier form: a zero
native balance is a level, not an edge, and nothing on that path refunds gas,
so it re-fired on every later top-up and discarded what it had just recorded.
An identity that the reset itself writes cannot do that."
```

---

### Task 2: Value every account that has traded

**Files:**
- Modify: `agentpit/db/table_create.py`
- Modify: `agentpit/db/table_read.py`, `agentpit/db/table_write.py`
- Create: `agentpit/services/leaderboard_service.py`
- Create: `tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `AccountService.total_value`, `OnchainAdmin.usd_balance`, `TableRead.get_total_deposited`.
- Produces: `TableRead.list_traded_accounts(db) -> list[TradedAccount]`; `TableWrite.insert_account_snapshot(db, user_id, t, capital_raw, deposited_raw)`; `TableWrite.prune_account_snapshots(db, older_than) -> int`; `LeaderboardService.take_snapshot(now) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_leaderboard.py`:

```python
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn, fresh_test_db


def test_only_accounts_that_traded_are_listed():
    """An account with no trade has nothing to rank, and listing every
    registered address would put people on a public board by default."""
    conn = fresh_test_conn()
    traded_id, traded_acct, traded_key = TableWrite.create_user(
        conn, email="traded@example.com", password_hash="x", handle="trader"
    )
    idle_id, _idle_acct, _idle_key = TableWrite.create_user(
        conn, email="idle@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t1", traded_key, 1_700_000_000),
    )

    rows = TableRead.list_traded_accounts(conn)
    ids = {r.user_id for r in rows}
    assert traded_id in ids
    assert idle_id not in ids
    assert traded_acct is not None
    conn.close()


def test_the_house_is_not_a_competitor():
    """It is the counterparty to nearly every trade on the platform. Ranking
    the market maker against the people trading against it is meaningless."""
    conn = fresh_test_conn()
    house_id, _acct, house_key = TableWrite.create_user(
        conn, email="house@example.com", password_hash="x", handle=None
    )
    TableWrite.mark_user_as_bot(conn, house_key)
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t2", house_key, 1_700_000_000),
    )

    assert house_id not in {r.user_id for r in TableRead.list_traded_accounts(conn)}
    conn.close()


def test_snapshots_round_trip_and_prune():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="snap@example.com", password_hash="x", handle=None
    )
    TableWrite.insert_account_snapshot(conn, user_id, 1_000, 111, 222)
    TableWrite.insert_account_snapshot(conn, user_id, 2_000, 333, 444)

    latest = TableRead.latest_account_snapshots(conn)
    assert latest[user_id] == (333, 444), "the most recent row wins"

    assert TableWrite.prune_account_snapshots(conn, older_than=1_500) == 1
    conn.close()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_leaderboard.py -q
```

Expected: `AttributeError: type object 'TableRead' has no attribute 'list_traded_accounts'`.

- [ ] **Step 3: Add the table**

In `agentpit/db/table_create.py`, add beside `create_price_snapshots_table`:

```python
    @staticmethod
    def create_account_snapshots_table(conn: psycopg.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_snapshots (
                SNAPSHOT_ID BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                USER_ID TEXT NOT NULL,
                T BIGINT NOT NULL,
                CAPITAL_RAW BIGINT NOT NULL,
                DEPOSITED_RAW BIGINT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_account_snapshots_user_t "
            "ON account_snapshots(USER_ID, T DESC)"
        )
```

and call it from `create_all_tables`, beside the `create_price_snapshots_table(conn)` call:

```python
        TableCreate.create_account_snapshots_table(conn)
```

`DEPOSITED_RAW` is stored alongside capital so each snapshot is self-contained: the sparkline can show *return* over time, which is what the default sort ranks on, rather than a bare balance.

- [ ] **Step 4: Add the reads and writes**

In `agentpit/db/table_read.py`, add near the other user reads (put the dataclass at module level, above the `TableRead` class):

```python
@dataclass(frozen=True)
class TradedAccount:
    user_id: str
    eth_address: str
    handle: str | None
```

with `from dataclasses import dataclass` at the top of the file if absent, then inside `TableRead`:

```python
    @staticmethod
    def list_traded_accounts(db: psycopg.Connection) -> "list[TradedAccount]":
        """Every non-house account with at least one trade, taker or maker.

        Having traded is the membership rule: it keeps every registered
        address off a public board by default, and an account that never
        traded has nothing to rank. The house is excluded because it is the
        counterparty to nearly every trade rather than a competitor.
        """
        rows = db.execute(
            """
            SELECT DISTINCT u.USER_ID, u.ETH_ADDRESS, u.HANDLE
            FROM users u
            JOIN trades t
              ON t.TAKER_API_KEY = u.API_KEY OR t.MAKER_API_KEY = u.API_KEY
            WHERE u.IS_BOT = 0
            """
        ).fetchall()
        return [
            TradedAccount(
                user_id=r["USER_ID"],
                eth_address=r["ETH_ADDRESS"],
                handle=r["HANDLE"],
            )
            for r in rows
        ]

    @staticmethod
    def latest_account_snapshots(
        db: psycopg.Connection,
    ) -> "dict[str, tuple[int, int]]":
        """user_id -> (capital_raw, deposited_raw) from each account's newest row."""
        rows = db.execute(
            """
            SELECT DISTINCT ON (USER_ID) USER_ID, CAPITAL_RAW, DEPOSITED_RAW
            FROM account_snapshots
            ORDER BY USER_ID, T DESC
            """
        ).fetchall()
        return {
            r["USER_ID"]: (int(r["CAPITAL_RAW"]), int(r["DEPOSITED_RAW"]))
            for r in rows
        }
```

In `agentpit/db/table_write.py`:

```python
    @staticmethod
    def insert_account_snapshot(
        db: psycopg.Connection,
        user_id: str,
        t: int,
        capital_raw: int,
        deposited_raw: int,
    ) -> None:
        db.execute(
            "INSERT INTO account_snapshots "
            "(USER_ID, T, CAPITAL_RAW, DEPOSITED_RAW) VALUES (%s, %s, %s, %s)",
            (user_id, t, capital_raw, deposited_raw),
        )

    @staticmethod
    def prune_account_snapshots(db: psycopg.Connection, older_than: int) -> int:
        cur = db.execute(
            "DELETE FROM account_snapshots WHERE T < %s", (older_than,)
        )
        return cur.rowcount
```

- [ ] **Step 5: Write the service**

Create `agentpit/services/leaderboard_service.py`:

```python
"""Valuing every trading account on a timer, so ranking never reads the chain."""
import logging

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.account_service import AccountService

log = logging.getLogger(__name__)


class LeaderboardService:
    """Writes one snapshot row per trading account per pass.

    Valuing an account walks its positions on chain, so this cannot happen on
    read: the Arena polls every four seconds, and pagination would not help --
    to know who belongs on page one you must value everyone.
    """

    def __init__(
        self,
        db: DbSession,
        onchain: OnchainAdmin,
        accounts: AccountService,
        settings: Settings,
    ):
        self._db = db
        self._onchain = onchain
        self._accounts = accounts
        self._settings = settings

    def _capital_raw(self, address: str) -> int:
        cash = self._onchain.usd_balance(address)
        rows = self._accounts.total_value(address)
        value_whole = rows[0]["value"] if rows else 0.0
        return cash + int(round(value_whole * 10**6))

    def take_snapshot(self, now: int) -> int:
        """Value every trading account. Returns the number of rows written.

        One account failing must not lose the whole pass -- a single unreadable
        position would otherwise cost every other account its data point.
        """
        with self._db.read() as conn:
            accounts = TableRead.list_traded_accounts(conn)

        written = 0
        for account in accounts:
            try:
                capital = self._capital_raw(account.eth_address)
            except Exception:
                log.exception("valuing %s failed", account.user_id)
                continue
            with self._db.write() as conn:
                deposited = TableRead.get_total_deposited(
                    conn, account.user_id, self._settings.paper_balance_target_raw
                )
                TableWrite.insert_account_snapshot(
                    conn, account.user_id, now, capital, deposited
                )
            written += 1
        return written
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_leaderboard.py -q
```

Expected: 3 passed.

- [ ] **Step 7: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py agentpit/db/table_write.py \
        agentpit/services/leaderboard_service.py tests/test_leaderboard.py
git commit -m "feat(leaderboard): value every trading account on a timer

Valuing an account walks its positions on chain, so ranking cannot happen on
read -- the Arena polls every four seconds, and paging would limit what is
sent rather than what is computed. One snapshot row per account per pass,
carrying deposited alongside capital so the curve can show return rather than
a bare balance. Membership is having traded, which keeps every registered
address off a public board by default; the house is excluded because it is the
counterparty to nearly every trade rather than a competitor."
```

---

### Task 3: The board, and the endpoint that serves it

**Files:**
- Modify: `agentpit/services/leaderboard_service.py`
- Create: `agentpit/api/routes/leaderboard.py`
- Modify: `agentpit/api/deps.py`, `agentpit/api/main.py` (router registration), `agentpit/api/app.py` (the timer)
- Modify: `agentpit/config.py`
- Modify: `tests/test_leaderboard.py`
- Create: `tests/api/test_leaderboard_endpoint.py`

**Interfaces:**
- Consumes: `LeaderboardService.take_snapshot`, `TableRead.latest_account_snapshots`, `TableRead.list_traded_accounts`.
- Produces: `display_name(handle, eth_address) -> str`; `rank_rows(rows, sort) -> list[LeaderboardRow]`; `LeaderboardService.build_board() -> list[LeaderboardRow]`; `GET /leaderboard?sort=`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_leaderboard.py`:

```python
from agentpit.services.leaderboard_service import (
    LeaderboardRow,
    display_name,
    rank_rows,
)


def _row(name, capital, deposited, trades=1, is_house_agent=False):
    return LeaderboardRow(
        name=name,
        address="0x" + "11" * 20,
        capital_raw=capital,
        deposited_raw=deposited,
        trades=trades,
        is_house_agent=is_house_agent,
    )


def test_earned_and_return_come_off_capital_and_deposits():
    row = _row("a", capital=120_000_000_000, deposited=100_000_000_000)
    assert row.earned_raw == 20_000_000_000
    assert row.return_pct == 20.0


def test_return_is_zero_rather_than_dividing_by_zero():
    """Cannot happen once the signup grant counts as the first deposit, which
    is exactly why it does. Pinned so that stays true."""
    assert _row("a", capital=5, deposited=0).return_pct == 0.0


def test_default_sort_is_return_not_capital():
    """The default sort is what 'the leaderboard' means to a visitor, and
    capital alone ranks whoever pressed the top-up button most."""
    big_pile = _row("whale", capital=900_000_000_000, deposited=900_000_000_000)
    good_trader = _row("sharp", capital=150_000_000_000, deposited=100_000_000_000)
    assert [r.name for r in rank_rows([big_pile, good_trader], "return")] == [
        "sharp",
        "whale",
    ]
    assert [r.name for r in rank_rows([big_pile, good_trader], "capital")] == [
        "whale",
        "sharp",
    ]


def test_the_name_is_the_handle_or_the_truncated_address():
    assert display_name("degen_trader", "0x" + "ab" * 20) == "degen_trader"
    assert display_name(None, "0x1234567890abcdef1234567890abcdef12345678") == (
        "0x1234…5678"
    )
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_leaderboard.py -q -k "earned or return or sort or name"
```

Expected: `ImportError: cannot import name 'LeaderboardRow'`.

- [ ] **Step 3: Add the row, the name and the ranking**

Add to `agentpit/services/leaderboard_service.py`, above the service class:

```python
from pydantic import BaseModel

SORTS = ("return", "earned", "capital", "trades")


class LeaderboardRow(BaseModel):
    name: str
    address: str
    capital_raw: int
    deposited_raw: int
    trades: int
    is_house_agent: bool

    @property
    def earned_raw(self) -> int:
        return self.capital_raw - self.deposited_raw

    @property
    def return_pct(self) -> float:
        """Percent return on what the account was handed.

        Zero deposits cannot happen once the signup grant counts as the first
        one -- which is why it does -- but a board that divides by zero on an
        edge case is worse than one that shows 0%.
        """
        if self.deposited_raw <= 0:
            return 0.0
        return 100.0 * self.earned_raw / self.deposited_raw


def display_name(handle: str | None, eth_address: str) -> str:
    """The handle when set, otherwise a truncated address.

    Never the email: nobody is put on a public board under the address they
    signed up with. Nobody drops off the board for leaving the handle blank
    either -- that would hide exactly the accounts that have not yet noticed
    the field exists.
    """
    if handle and handle.strip():
        return handle
    return f"{eth_address[:6]}…{eth_address[-4:]}"


def rank_rows(rows: "list[LeaderboardRow]", sort: str) -> "list[LeaderboardRow]":
    """Order the board. Unknown sorts fall back to return, the default."""
    keys = {
        "return": lambda r: (r.return_pct, r.earned_raw),
        "earned": lambda r: (r.earned_raw, r.return_pct),
        "capital": lambda r: (r.capital_raw, r.earned_raw),
        "trades": lambda r: (r.trades, r.return_pct),
    }
    key = keys.get(sort, keys["return"])
    return sorted(rows, key=key, reverse=True)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_leaderboard.py -q -k "earned or return or sort or name"
```

Expected: 4 passed.

- [ ] **Step 5: Assemble and cache the board**

Add to `LeaderboardService`:

```python
    def build_board(self) -> "list[LeaderboardRow]":
        """Assemble the board from the latest snapshot of each account.

        Reads only the database -- the chain work happened in `take_snapshot`.
        """
        with self._db.read() as conn:
            accounts = TableRead.list_traded_accounts(conn)
            latest = TableRead.latest_account_snapshots(conn)
            counts = TableRead.count_trades_by_user(conn)

        rows = []
        for account in accounts:
            snapshot = latest.get(account.user_id)
            if snapshot is None:
                # Traded, but the valuation pass has not reached it yet.
                continue
            capital, deposited = snapshot
            rows.append(
                LeaderboardRow(
                    name=display_name(account.handle, account.eth_address),
                    address=account.eth_address,
                    capital_raw=capital,
                    deposited_raw=deposited,
                    trades=counts.get(account.user_id, 0),
                    is_house_agent=account.is_house_agent,
                )
            )
        return rows
```

Add `count_trades_by_user` to `agentpit/db/table_read.py`:

```python
    @staticmethod
    def count_trades_by_user(db: psycopg.Connection) -> "dict[str, int]":
        rows = db.execute(
            """
            SELECT u.USER_ID AS UID, COUNT(*) AS N
            FROM users u
            JOIN trades t
              ON t.TAKER_API_KEY = u.API_KEY OR t.MAKER_API_KEY = u.API_KEY
            GROUP BY u.USER_ID
            """
        ).fetchall()
        return {r["UID"]: int(r["N"]) for r in rows}
```

Our five personalities are marked by their handle appearing in `Settings.house_agent_handles`; add that setting to `agentpit/config.py` beside the other product settings:

```python
    # The five Arena personalities are ours: they fork one shared analysis
    # rather than reasoning independently, and they sit next to agents that
    # do. Labelled on the board rather than hidden from it.
    house_agent_handles: list[str] = Field(
        default=["bold", "cautious", "contrarian", "hybrid", "longshot"],
        validation_alias="AGENTPIT_HOUSE_AGENT_HANDLES",
    )
```

`is_house_agent` is computed in `build_board` as `account.handle in self._settings.house_agent_handles` — not stored on `TradedAccount` and not filtered in SQL, so the setting stays the single source and changing it needs no migration.

- [ ] **Step 6: Add the endpoint**

Create `agentpit/api/routes/leaderboard.py`:

```python
"""The public board. Served from memory; the chain work happens on a timer."""
import time

from fastapi import APIRouter, Query
from pydantic import BaseModel

from agentpit.api.deps import LeaderboardServiceDep
from agentpit.services.leaderboard_service import SORTS, rank_rows

router = APIRouter(tags=["leaderboard"])

# Same shape as routes/events.py's listing cache: the board only changes when
# the valuation pass runs, and the Arena polls every four seconds.
_CACHE_TTL_SECONDS = 30.0
_board_cache: "dict[str, tuple[float, list[dict]]]" = {}


class LeaderboardEntry(BaseModel):
    rank: int
    name: str
    address: str
    capital: str
    earned: str
    returnPct: float
    trades: int
    isHouseAgent: bool


class LeaderboardResponse(BaseModel):
    sort: str
    entries: "list[LeaderboardEntry]"


@router.get("/leaderboard", response_model=LeaderboardResponse)
def get_leaderboard(
    service: LeaderboardServiceDep,
    sort: str = Query(default="return"),
) -> LeaderboardResponse:
    """Rank every account that has traded.

    `sort` is one of return, earned, capital, trades; anything else falls back
    to return. Amounts are base-unit integer strings, matching the rest of the
    API. No email address appears in this payload under any sort.
    """
    key = sort if sort in SORTS else "return"
    now = time.monotonic()
    hit = _board_cache.get(key)
    if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
        return LeaderboardResponse(sort=key, entries=hit[1])

    ranked = rank_rows(service.build_board(), key)
    entries = [
        LeaderboardEntry(
            rank=i + 1,
            name=row.name,
            address=row.address,
            capital=str(row.capital_raw),
            earned=str(row.earned_raw),
            returnPct=round(row.return_pct, 2),
            trades=row.trades,
            isHouseAgent=row.is_house_agent,
        ).model_dump()
        for i, row in enumerate(ranked)
    ]
    _board_cache[key] = (now, entries)
    return LeaderboardResponse(sort=key, entries=entries)
```

Register the router where the others are registered in `agentpit/api/main.py` (or `app.py` — follow whichever file lists `markets`, `events` and `users`), and add the dependency to `agentpit/api/deps.py` following `get_balance_service`:

```python
def get_leaderboard_service(
    db: SessionDep,
    onchain: OnchainAdminDep,
    accounts: AccountServiceDep,
    settings: SettingsDep,
) -> LeaderboardService:
    return LeaderboardService(db, onchain, accounts, settings)


LeaderboardServiceDep = Annotated[
    LeaderboardService, Depends(get_leaderboard_service)
]
```

- [ ] **Step 7: Add the timer**

In `agentpit/config.py`, beside the snapshot settings:

```python
    leaderboard_enabled: bool = Field(
        default=True, validation_alias="AGENTPIT_LEADERBOARD_ENABLED"
    )
    leaderboard_interval_seconds: int = Field(
        default=300, validation_alias="AGENTPIT_LEADERBOARD_INTERVAL_SECONDS"
    )
```

In `agentpit/api/app.py`, add a loop modelled exactly on `_snapshot_loop` (around line 305) and start it beside `snapshot_task` (around line 381), cancelling it in the same shutdown block the other tasks use:

```python
async def _leaderboard_loop(
    service: LeaderboardService, interval_seconds: int
) -> None:
    while True:
        try:
            written = await asyncio.to_thread(
                service.take_snapshot, int(time.time())
            )
            log.info("Leaderboard tick: %d accounts valued", written)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Leaderboard tick failed")
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 8: Write the endpoint tests**

Create `tests/api/test_leaderboard_endpoint.py`:

```python
from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_leaderboard_is_public():
    """No key needed: it is a public board, like /positions and /value."""
    with TestClient(app) as client:
        assert client.get("/leaderboard").status_code == 200


def test_no_email_appears_in_the_payload():
    """Nobody is put on a public board under the address they signed up with.
    Asserted against the raw body so a nested field cannot slip one through."""
    with TestClient(app) as client:
        body = client.get("/leaderboard").text
    assert "@" not in body


def test_unknown_sort_falls_back_to_return():
    with TestClient(app) as client:
        assert client.get("/leaderboard?sort=nonsense").json()["sort"] == "return"
```

- [ ] **Step 9: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add agentpit/services/leaderboard_service.py agentpit/api/routes/leaderboard.py \
        agentpit/api/deps.py agentpit/api/main.py agentpit/api/app.py \
        agentpit/config.py agentpit/db/table_read.py \
        tests/test_leaderboard.py tests/api/test_leaderboard_endpoint.py
git commit -m "feat(api): GET /leaderboard

Four sorts, defaulting to return -- the default is what the board means to a
visitor, and capital alone ranks whoever pressed the top-up button most.
Served from a short-lived cache because the Arena polls every four seconds
while the underlying figures change only when the valuation pass runs. Our
five personalities are labelled rather than hidden: they fork one shared
analysis and will be sitting next to agents that do not."
```

---

### Task 4: The Arena reads the endpoint

**Files:**
- Modify: `ui/src/api/leaderboard.ts`
- Modify: `ui/src/pages/AgentArenaPage.tsx`
- Modify: `ui/src/api/leaderboard.test.ts`

**Interfaces:**
- Consumes: `GET /leaderboard?sort=` from Task 3.
- Produces: `useLeaderboard(sort)`; `LEADERBOARD_SORTS`.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/api/leaderboard.test.ts`:

```ts
import { formatBoardAmount, LEADERBOARD_SORTS } from "./leaderboard";

describe("leaderboard board data", () => {
  it("offers the four sorts, return first", () => {
    expect(LEADERBOARD_SORTS.map((s) => s.key)).toEqual([
      "return",
      "earned",
      "capital",
      "trades",
    ]);
  });

  it("renders base-unit strings as dollars", () => {
    expect(formatBoardAmount("100000000000")).toBe("$100,000.00");
    expect(formatBoardAmount("-2500000")).toBe("-$2.50");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ui && npx vitest run src/api/leaderboard.test.ts
```

Expected: FAIL — `LEADERBOARD_SORTS` is not exported.

- [ ] **Step 3: Add the fetch layer**

Append to `ui/src/api/leaderboard.ts`:

```ts
export interface BoardEntry {
  rank: number;
  name: string;
  address: string;
  capital: string;
  earned: string;
  returnPct: number;
  trades: number;
  isHouseAgent: boolean;
}

export interface BoardResponse {
  sort: string;
  entries: BoardEntry[];
}

export const LEADERBOARD_SORTS = [
  { key: "return", label: "Return" },
  { key: "earned", label: "Earned" },
  { key: "capital", label: "Capital" },
  { key: "trades", label: "Trades" },
] as const;

const BOARD_USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Base-unit integer string (6 decimals) to dollars. */
export function formatBoardAmount(raw: string): string {
  return BOARD_USD.format(Number(raw) / 1e6);
}

export function useLeaderboard(sort: string) {
  return useQuery({
    queryKey: ["leaderboard", sort],
    queryFn: () =>
      apiFetch<BoardResponse>(`/leaderboard?sort=${encodeURIComponent(sort)}`),
    refetchInterval: 30_000,
  });
}
```

Add `import { apiFetch } from "@/api/client";` to the top of the file if it is not already there.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ui && npx vitest run src/api/leaderboard.test.ts
```

Expected: PASS.

- [ ] **Step 5: Render the board**

In `ui/src/pages/AgentArenaPage.tsx`, replace the static-file leaderboard table with one driven by `useLeaderboard`. Keep the page's existing visual language — the same card, medal and typography treatment it already uses — and add a sort control built from `LEADERBOARD_SORTS`, defaulting to `return`.

Each row shows: rank, name, the four figures, and a small "ours" label when `isHouseAgent` is true. **Do not render the address as the primary label when a name exists**, and never render anything not present in `BoardEntry`.

Leave the per-agent `bot-status-<id>.json` panels alone — they carry reasoning detail this endpoint does not replace.

- [ ] **Step 6: Run the full UI chain**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

Expected: all tests pass, typecheck clean, **0 lint errors** (3 pre-existing warnings), build succeeds.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/leaderboard.ts ui/src/api/leaderboard.test.ts ui/src/pages/AgentArenaPage.tsx
git commit -m "feat(ui): the Arena ranks from the API, not a static file

The board was a picture of leaderboard.json, written by our own bot against a
different machine's database -- production's copy was three weeks old, and a
user who followed the builder guide could never appear in it. It now reads
GET /leaderboard, with the four sorts and the same default: return."
```

---

## Self-review

**Spec coverage.** Timed pass into `account_snapshots` with deposited stored alongside capital → Task 2. In-memory board → Task 3 Step 6. Membership (traded, house excluded) → Task 2 Steps 1, 4. Our five labelled → Task 3 Step 5. Handle-or-address, never email → Task 3 Steps 3, 8. Four columns defaulting to return → Task 3. Deployment identity as the edge signal, lifting the launch-plan precondition → Task 1. Arena off the static file → Task 4. Pointing the bots at production is Out of scope in the spec and has no task, by design.

**Placeholders.** None. Task 4 Step 5 describes the render in prose rather than giving markup, because the page's existing visual language is the requirement and reproducing it here would drift from the file; it names the file, the hook, the fields and the two rules that matter.

**Type consistency.** `LeaderboardRow{name, address, capital_raw, deposited_raw, trades, is_house_agent}` with `earned_raw` and `return_pct` derived; the wire shape is `LeaderboardEntry{rank, name, address, capital, earned, returnPct, trades, isHouseAgent}` — raw ints inside, base-unit strings for amounts on the wire, matching `/balance-allowance` and `/me/top-up`. The TypeScript `BoardEntry` mirrors it field for field. `SORTS` in Python and `LEADERBOARD_SORTS` in TypeScript carry the same four keys in the same order. `TradedAccount{user_id, eth_address, handle}` is produced in Task 2 and consumed in Task 3, which derives `is_house_agent` from the handle rather than storing it — the one inconsistency this review caught, since an earlier draft added the field to the dataclass as well.
