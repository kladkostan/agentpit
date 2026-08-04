# Net Worth Threshold and Deposit Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the top-up from handing out the full grant every day to anyone who moves cash into positions first, and record what each account was granted so the leaderboard can rank earnings rather than handouts.

**Architecture:** `BalanceService` gains an `AccountService` and compares the target against cash *plus position value* instead of cash alone. A new `users.TOTAL_DEPOSITED` column is written at onboarding from the balance actually on chain, and incremented inside the same atomic UPDATE that claims the daily cooldown.

**Tech Stack:** Python 3.13 / FastAPI / psycopg3 / pydantic.

## Global Constraints

- apUSD is **6-decimal**. Every stored and on-chain figure is raw: $100,000 = `100_000_000_000`.
- `AccountService.total_value(address)` returns `[{"user": address, "value": <float whole apUSD>}]`. Raw conversion is `int(round(value * 10**6))`.
- **`GET /me/top-up` must make no chain call.** It is a database read the profile page issues on load. `tests/api/test_topup.py` installs a fake `OnchainAdmin` whose `usd_balance` **raises**; that tripwire must stay green.
- A no-op top-up (already at or above target) must **not** consume the day's allowance.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` from the repo root. **NEVER source `.env`** — conftest setdefaults get defeated and live-sync tests hang. Suite is currently **418 passed** and must end green.
- Commit messages carry **no AI attribution trailer**. Stage files by name; never `git add -A`.

---

### Task 1: The threshold moves from cash to net worth

**Files:**
- Modify: `agentpit/services/balance_service.py`
- Modify: `agentpit/api/deps.py:118-121`
- Modify: `tests/test_balance_topup.py`

**Interfaces:**
- Consumes: `AccountService.total_value(eth_address) -> list[dict]` (`agentpit/services/account_service.py:185`), `AccountService(db, onchain)`.
- Produces: `BalanceService(db, onchain, settings, accounts)`; `BalanceService._net_worth_raw(address) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_balance_topup.py`:

```python
def test_positions_count_toward_the_target():
    """The bug this closes: cash alone made the top-up farmable.

    Move the whole balance into positions and cash reads zero, so the
    shortfall reads as the entire grant -- every day, for ever. Measured on a
    live instance before this fix: three presses reached $400k.
    """
    from agentpit.services.balance_service import BalanceService

    TARGET = 100_000_000_000

    class _Accounts:
        def __init__(self, value_whole):
            self.value_whole = value_whole

        def total_value(self, address):
            return [{"user": address, "value": self.value_whole}]

    class _Onchain:
        def __init__(self, cash):
            self.cash = cash
            self.mints = []

        def usd_balance(self, address):
            return self.cash

        def mint_to(self, address, amount_raw, *, timeout=30):
            self.mints.append(amount_raw)

    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="networth@example.com", password_hash="x", handle=None
    )
    user = TableRead.get_user_by_userid(conn, user_id)
    conn.close()

    settings = Settings()
    # Everything is in positions: cash 0, positions worth the full target.
    onchain = _Onchain(cash=0)
    svc = BalanceService(fresh_test_db(), onchain, settings, _Accounts(100_000.0))
    result = svc.top_up(user, now=1_700_000_000)

    assert result.minted_raw == 0, "net worth is at target -- nothing was lost"
    assert onchain.mints == []
    assert acct is not None


def test_positions_below_target_mint_only_the_shortfall():
    from agentpit.services.balance_service import BalanceService

    class _Accounts:
        def total_value(self, address):
            return [{"user": address, "value": 60_000.0}]

    class _Onchain:
        def __init__(self):
            self.mints = []

        def usd_balance(self, address):
            return 0

        def mint_to(self, address, amount_raw, *, timeout=30):
            self.mints.append(amount_raw)

    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="shortfall@example.com", password_hash="x", handle=None
    )
    user = TableRead.get_user_by_userid(conn, user_id)
    conn.close()

    onchain = _Onchain()
    svc = BalanceService(fresh_test_db(), onchain, Settings(), _Accounts())
    result = svc.top_up(user, now=1_700_000_000)

    # Worth $60k, target $100k -> mint exactly the $40k gap.
    assert result.minted_raw == 40_000_000_000
    assert onchain.mints == [40_000_000_000]
```

Add `from agentpit.config import Settings` to the imports at the top of the file if it is not already there.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "positions"
```

Expected: `TypeError: BalanceService.__init__() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3: Take the AccountService and compute net worth**

In `agentpit/services/balance_service.py`, add the import:

```python
from agentpit.services.account_service import AccountService
```

Replace the constructor:

```python
    def __init__(
        self,
        db: DbSession,
        onchain: OnchainAdmin,
        settings: Settings,
        accounts: AccountService,
    ):
        self._db = db
        self._onchain = onchain
        self._settings = settings
        self._accounts = accounts
```

Add this method directly after `next_allowed`:

```python
    def _net_worth_raw(self, address: str) -> int:
        """Cash plus what the open positions are currently worth, raw.

        Cash alone is what made the top-up farmable: move it into positions and
        the shortfall reads as the whole grant, so pressing the button daily
        grew net worth without limit. What a demo balance restores is what the
        account is worth, and positions are part of that.

        `total_value` walks positions on chain, which is why this is reached
        only from `top_up` -- a human-initiated call at most once a day -- and
        never from `next_allowed`, which the profile page issues on load.
        """
        cash = self._onchain.usd_balance(address)
        rows = self._accounts.total_value(address)
        value_whole = rows[0]["value"] if rows else 0.0
        return cash + int(round(value_whole * 10**6))
```

- [ ] **Step 4: Point the threshold at it**

Still in `top_up`, replace the first statement and the `minted` computation. The balance read becomes a net-worth read:

```python
    def top_up(self, user: User, now: int) -> TopUpResult:
        # Net worth first: every early return below still needs to report it.
        # This is cash PLUS positions -- see _net_worth_raw for why.
        balance = self._net_worth_raw(user.eth_address)
```

Leave the rest of the method exactly as it is: `minted = topup_amount_raw(balance, ...)` now compares against net worth, and `balance_raw` in every `TopUpResult` now reports net worth rather than cash, which is the figure the decision was made on.

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "positions"
```

Expected: 2 passed.

- [ ] **Step 6: Wire the dependency**

In `agentpit/api/deps.py`, replace `get_balance_service`:

```python
def get_balance_service(
    db: SessionDep,
    onchain: OnchainAdminDep,
    settings: SettingsDep,
    accounts: AccountServiceDep,
) -> BalanceService:
    return BalanceService(db, onchain, settings, accounts)
```

`AccountServiceDep` is already defined at `deps.py:124`. If it is declared *below* `get_balance_service` in the file, move the `AccountServiceDep` assignment above it — a bare name is resolved at call time by FastAPI but the annotation is evaluated at import.

- [ ] **Step 7: Fix the other constructions of BalanceService**

```bash
grep -rn "BalanceService(" agentpit tests
```

Every call site needs the fourth argument. In `tests/api/test_topup.py` the fake `OnchainAdmin` has a `usd_balance` that **raises on purpose** — that tripwire proves the GET makes no chain call and must keep working. If a fake `AccountService` is needed there, give its `total_value` the same raising behaviour, so the GET is still proven not to reach either collaborator.

- [ ] **Step 8: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green, 418 + the new tests.

- [ ] **Step 9: Commit**

```bash
git add agentpit/services/balance_service.py agentpit/api/deps.py tests/test_balance_topup.py tests/api/test_topup.py
git commit -m "fix(balance): the top-up threshold counts positions, not just cash

Cash alone is zero at click time once it has been moved into positions, so the
shortfall read as the entire grant every day and net worth grew without limit.
Measured on a live instance before this: three presses reached \$400k. The
target is now compared against cash plus position value, which is what a demo
balance was always meant to restore. The mint is still cash and still tops up
TO the target, never by a fixed sum."
```

---

### Task 2: Record what each account was granted

**Files:**
- Modify: `agentpit/db/table_create.py` (the `additions` list in `_migrate_users_table`)
- Modify: `agentpit/db/table_read.py` (add `get_total_deposited`)
- Modify: `agentpit/db/table_write.py` (`claim_topup`, `release_topup`, `set_total_deposited`)
- Modify: `agentpit/services/balance_service.py`
- Modify: `agentpit/services/auth_service.py`
- Modify: `tests/test_balance_topup.py`

**Interfaces:**
- Produces: `TableRead.get_total_deposited(db, user_id, default_raw) -> int`; `TableWrite.set_total_deposited(db, user_id, raw)`; `TableWrite.claim_topup(db, user_id, at, not_before, deposit_raw) -> bool`; `TableWrite.release_topup(db, user_id, last, deposit_raw)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_balance_topup.py`:

```python
def test_deposits_accumulate_across_top_ups():
    """The leaderboard ranks capital minus what the account was handed.

    Without this column 'earned' cannot be computed at all, and relative
    return divides by zero for anyone who never pressed the button -- which is
    why the signup grant counts as the first deposit rather than as profit.
    """
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="deposits@example.com", password_hash="x", handle=None
    )

    GRANT = 100_000_000_000
    # Nothing recorded yet: reads as the grant rather than as zero.
    assert TableRead.get_total_deposited(conn, user_id, GRANT) == GRANT

    TableWrite.set_total_deposited(conn, user_id, GRANT)
    assert TableRead.get_total_deposited(conn, user_id, GRANT) == GRANT

    # Two top-ups of $40k and $25k.
    assert TableWrite.claim_topup(conn, user_id, 1_700_000_000, 0, 40_000_000_000)
    assert TableWrite.claim_topup(
        conn, user_id, 1_700_100_000, 1_700_000_000, 25_000_000_000
    )
    assert TableRead.get_total_deposited(conn, user_id, GRANT) == (
        GRANT + 40_000_000_000 + 25_000_000_000
    )
    conn.close()


def test_releasing_a_claim_also_takes_the_deposit_back():
    """A mint that never landed must leave no trace: not the day, not the
    deposit. Otherwise a failed top-up quietly worsens the user's ranking."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="release@example.com", password_hash="x", handle=None
    )
    GRANT = 100_000_000_000
    TableWrite.set_total_deposited(conn, user_id, GRANT)

    assert TableWrite.claim_topup(conn, user_id, 1_700_000_000, 0, 40_000_000_000)
    TableWrite.release_topup(conn, user_id, None, 40_000_000_000)

    assert TableRead.get_last_topup_at(conn, user_id) is None
    assert TableRead.get_total_deposited(conn, user_id, GRANT) == GRANT
    conn.close()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "deposit or releasing"
```

Expected: `AttributeError: type object 'TableRead' has no attribute 'get_total_deposited'`.

- [ ] **Step 3: Add the column**

In `agentpit/db/table_create.py`, append to the `additions` list in `_migrate_users_table`:

```python
            ("TOTAL_DEPOSITED", "BIGINT"),
```

- [ ] **Step 4: Add the read**

In `agentpit/db/table_read.py`, beside `get_last_topup_at`:

```python
    @staticmethod
    def get_total_deposited(
        db: psycopg.Connection, user_id: str, default_raw: int
    ) -> int:
        """Raw apUSD this account has been handed, grant included.

        NULL means the row predates the column. It reads as `default_raw` --
        the signup grant -- because a backfill migration could only have
        written the same number, and doing it at the read keeps the two
        production accounts and the house correct without one.
        """
        row = db.execute(
            "SELECT TOTAL_DEPOSITED FROM users WHERE USER_ID = %s", (user_id,)
        ).fetchone()
        if row is None or row["TOTAL_DEPOSITED"] is None:
            return default_raw
        return int(row["TOTAL_DEPOSITED"])
```

- [ ] **Step 5: Fold the deposit into the atomic claim**

In `agentpit/db/table_write.py`, replace `claim_topup` and add `release_topup` and `set_total_deposited`:

```python
    @staticmethod
    def claim_topup(
        db: psycopg.Connection,
        user_id: str,
        at: int,
        not_before: int,
        deposit_raw: int,
    ) -> bool:
        """Take the day's top-up allowance and record the deposit, atomically.

        Returns False when another request already holds it. The predicate, the
        cooldown stamp and the deposit are one statement so two concurrent
        callers cannot both pass a check-then-write gap, and so a claim can
        never be recorded without its deposit.
        """
        cur = db.execute(
            "UPDATE users SET LAST_TOPUP_AT = %s, "
            "TOTAL_DEPOSITED = COALESCE(TOTAL_DEPOSITED, 0) + %s "
            "WHERE USER_ID = %s "
            "AND (LAST_TOPUP_AT IS NULL OR LAST_TOPUP_AT <= %s)",
            (at, deposit_raw, user_id, not_before),
        )
        return cur.rowcount == 1

    @staticmethod
    def release_topup(
        db: psycopg.Connection, user_id: str, last: int | None, deposit_raw: int
    ) -> None:
        """Undo a claim whose mint never landed — both halves of it."""
        db.execute(
            "UPDATE users SET LAST_TOPUP_AT = %s, "
            "TOTAL_DEPOSITED = COALESCE(TOTAL_DEPOSITED, 0) - %s "
            "WHERE USER_ID = %s",
            (last, deposit_raw, user_id),
        )

    @staticmethod
    def set_total_deposited(
        db: psycopg.Connection, user_id: str, raw: int
    ) -> None:
        db.execute(
            "UPDATE users SET TOTAL_DEPOSITED = %s WHERE USER_ID = %s",
            (raw, user_id),
        )
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_balance_topup.py -q -k "deposit or releasing"
```

Expected: 2 passed.

- [ ] **Step 7: Pass the minted amount through the service**

In `agentpit/services/balance_service.py`, `top_up` currently calls:

```python
            claimed = TableWrite.claim_topup(conn, user.user_id, now, not_before)
```

which becomes:

```python
            claimed = TableWrite.claim_topup(
                conn, user.user_id, now, not_before, minted
            )
```

and the release inside the `except`:

```python
                TableWrite.set_last_topup_at(conn, user.user_id, last)
```

becomes:

```python
                TableWrite.release_topup(conn, user.user_id, last, minted)
```

- [ ] **Step 8: Record the signup grant as the first deposit**

In `agentpit/services/auth_service.py`, the registration path calls `self._run_onboarding(acct)` and then marks the user onboarded (around line 55-60). Record the deposit in that same block, from the balance actually on chain:

```python
        with self._db.write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)
            # Read the granted amount off the chain rather than from config:
            # the grant is baked into an immutable contract by
            # scripts/deploy_exchange.sh, while paper_balance_target_raw is a
            # separate Settings field. They are documented to agree and today
            # they do, but they are two sources and either can move.
            TableWrite.set_total_deposited(
                conn, user_id, self._onchain.usd_balance(acct.address)
            )
```

Match the surrounding names — if the account variable is not called `acct`, use whatever that block already uses. Do **not** put this inside `_run_onboarding`: that function receives only a `LocalAccount` and has no `user_id`, and it is also called by `_maybe_reonboard`, where a re-grant after a chain wipe should reset the figure rather than add to it.

- [ ] **Step 9: Run the whole backend suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py agentpit/db/table_write.py \
        agentpit/services/balance_service.py agentpit/services/auth_service.py \
        tests/test_balance_topup.py
git commit -m "feat(balance): record what each account was granted

The leaderboard ranks capital minus handouts, and nothing recorded the second
number. TOTAL_DEPOSITED is written at onboarding from the balance actually on
chain -- not from config, since the grant lives in an immutable contract and
the target lives in Settings -- and incremented inside the same atomic UPDATE
that claims the daily cooldown, so a mint can never be recorded without its
deposit. NULL reads as the signup grant, which keeps the accounts that predate
the column correct without a backfill."
```

---

## Self-review

**Spec coverage.** Threshold on net worth → Task 1. Position value from the existing `AccountService`, and deliberately absent from the GET → Task 1 Steps 3, 7. `TOTAL_DEPOSITED` set from the chain at onboarding → Task 2 Step 8. Incremented per top-up, atomically with the claim → Task 2 Steps 5, 7. NULL reads as the grant → Task 2 Step 4. The leaderboard itself is out of scope in the spec and has no task.

**Placeholders.** None. Two steps say "match the surrounding names" (the auth_service block, the `AccountServiceDep` ordering) because the existing convention is the requirement; both name the file and the line.

**Type consistency.** `total_value` returns whole-apUSD floats and is converted once, in `_net_worth_raw`. Everything else — `deposit_raw`, `default_raw`, `TOTAL_DEPOSITED`, `minted` — is raw 6-decimal int. `claim_topup` gains a fifth parameter and every caller is updated in Task 2 Step 7; `release_topup` replaces the `set_last_topup_at` call on the failure path only, and `set_last_topup_at` itself stays for nothing else — check whether it still has a caller and leave it if the tests use it.
