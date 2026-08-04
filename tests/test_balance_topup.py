import threading
import time

import pytest

from agentpit.config import Settings
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.balance_service import (
    BalanceService,
    next_allowed_at,
    topup_amount_raw,
)
from tests.db_helpers import fresh_test_conn, fresh_test_db

TARGET = 100_000_000_000        # $100k, 6dp
DAY = 86_400


def test_below_target_mints_the_difference():
    assert topup_amount_raw(30_000_000_000, TARGET) == 70_000_000_000


def test_at_target_mints_nothing():
    assert topup_amount_raw(TARGET, TARGET) == 0


def test_above_target_mints_nothing_rather_than_clawing_back():
    """Someone who traded past the target has nothing to restore. That is a
    no-op, not an error, and certainly not a negative mint."""
    assert topup_amount_raw(TARGET + 1, TARGET) == 0


def test_the_result_never_exceeds_the_target():
    for balance in (0, 1, TARGET // 2, TARGET - 1, TARGET, TARGET * 3):
        assert balance + topup_amount_raw(balance, TARGET) == max(balance, TARGET)


def test_first_top_up_is_allowed_immediately():
    assert next_allowed_at(None, DAY) == 0


def test_a_second_top_up_waits_a_day():
    assert next_allowed_at(1_000_000, DAY) == 1_000_000 + DAY


def test_last_topup_at_round_trips():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="topup@example.com", password_hash="x", handle=None
    )
    assert TableRead.get_last_topup_at(conn, user_id) is None
    TableWrite.set_last_topup_at(conn, user_id, 1_700_000_000)
    assert TableRead.get_last_topup_at(conn, user_id) == 1_700_000_000
    conn.close()


# ----- claim_topup: the atomic claim, not a read-then-write pair -----------


def test_claim_topup_is_atomic():
    """A naive read-then-write can't fail this: the second call must lose
    because the row itself, not a value read earlier, decides eligibility."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="claim@example.com", password_hash="x", handle=None
    )
    now = 1_700_000_000
    not_before = now - DAY

    assert TableWrite.claim_topup(conn, user_id, now, not_before, 0) is True
    assert TableWrite.claim_topup(conn, user_id, now, not_before, 0) is False

    later = now + DAY
    assert TableWrite.claim_topup(conn, user_id, later, later - DAY, 0) is True
    conn.close()


# ----- BalanceService: the claim must actually stop a race -----------------


class _FakeOnchain:
    """usd_balance reflects mints already recorded, like a real faucet would."""

    def __init__(self, balance_raw: int):
        self.balance_raw = balance_raw
        self.mints: list[tuple[str, int]] = []
        self.fail_next_mint = False

    def usd_balance(self, address: str) -> int:
        return self.balance_raw

    def mint_to(self, recipient: str, amount_raw: int, *, timeout: int = 30):
        if self.fail_next_mint:
            self.fail_next_mint = False
            raise RuntimeError("mint failed")
        self.mints.append((recipient, amount_raw))
        self.balance_raw += amount_raw


class _NoPositions:
    """No open positions: net worth reduces to cash, matching these tests'
    pre-existing cash-only fixtures."""

    def total_value(self, address: str) -> list[dict]:
        return []


class _User:
    def __init__(self, user_id: str, eth_address: str):
        self.user_id = user_id
        self.eth_address = eth_address


def test_second_topup_in_the_window_mints_nothing():
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="race@example.com", password_hash="x", handle=None
    )
    conn.close()

    db = fresh_test_db()
    onchain = _FakeOnchain(balance_raw=30_000_000_000)
    service = BalanceService(db, onchain, Settings(), _NoPositions())
    user = _User(user_id, acct.address)
    now = 1_700_000_000

    first = service.top_up(user, now)
    second = service.top_up(user, now)

    assert len(onchain.mints) == 1
    assert first.minted_raw == 70_000_000_000
    assert second.minted_raw == 0
    assert second.balance_raw == onchain.balance_raw
    db.close()


def test_failed_mint_releases_the_claim():
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="rollback@example.com", password_hash="x", handle=None
    )
    conn.close()

    db = fresh_test_db()
    onchain = _FakeOnchain(balance_raw=30_000_000_000)
    onchain.fail_next_mint = True
    service = BalanceService(db, onchain, Settings(), _NoPositions())
    user = _User(user_id, acct.address)
    now = 1_700_000_000

    with pytest.raises(RuntimeError):
        service.top_up(user, now)
    assert onchain.mints == []

    retry = service.top_up(user, now)
    assert retry.minted_raw == 70_000_000_000
    assert len(onchain.mints) == 1
    db.close()


def test_topup_when_already_ahead_does_not_touch_last_topup_at():
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="ahead@example.com", password_hash="x", handle=None
    )
    conn.close()

    db = fresh_test_db()
    onchain = _FakeOnchain(balance_raw=TARGET + 1)
    service = BalanceService(db, onchain, Settings(), _NoPositions())
    user = _User(user_id, acct.address)

    result = service.top_up(user, 1_700_000_000)

    assert result.minted_raw == 0
    assert onchain.mints == []
    db.close()

    check = fresh_test_conn()
    assert TableRead.get_last_topup_at(check, user_id) is None
    check.close()


def test_cooldown_path_reports_the_real_next_allowed_at():
    """Ordinary in-cooldown path (no concurrent writer): a caller who is
    genuinely still on cooldown must be told the true wait time, never 0.

    This is a single sequential call, so it cannot distinguish code that
    reports the value read on entry from code that re-reads after a failed
    claim — both see the same row. It pins the contract for this path; the
    lost-claim race itself is covered separately by
    `test_concurrent_topups_only_mint_once`, which asserts on the loser's
    `next_allowed_at` under a genuine concurrent write."""
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="pinned@example.com", password_hash="x", handle=None
    )
    last_topup_at = 1_700_000_000
    TableWrite.set_last_topup_at(conn, user_id, last_topup_at)
    conn.close()

    db = fresh_test_db()
    onchain = _FakeOnchain(balance_raw=30_000_000_000)  # below target
    service = BalanceService(db, onchain, Settings(), _NoPositions())
    user = _User(user_id, acct.address)
    now = last_topup_at + 1  # inside the cooldown window

    result = service.top_up(user, now)

    assert result.minted_raw == 0
    assert onchain.mints == []
    assert result.next_allowed_at == last_topup_at + DAY
    db.close()


# ----- a genuine race: two real threads, two real connections --------------


def test_concurrent_topups_only_mint_once():
    """Two threads race BalanceService.top_up for the same user with the
    same `now`, each on its own pooled connection.

    This must FAIL against the pre-bf13bf9 code: with no atomic claim, both
    threads read LAST_TOPUP_AT before either writes it, both pass the gate,
    and both call mint_to. The barrier lines the threads up at the same
    starting line and the sleep inside mint_to holds that unlocked window
    open long enough for the second thread to walk through it. Against the
    atomic claim, only one thread's UPDATE can match the row's current
    state; the other's claim_topup call returns False and it never reaches
    mint_to at all — so exactly one mint lands no matter how the threads are
    scheduled.

    It also pins the loser's reported `next_allowed_at`. Both threads start
    from `last=None`, so code that reuses the value read on entry (the
    bf13bf9 lost-claim bug) would have the loser report `0` — "top up right
    now" — right after the winner just claimed the day. The fix re-reads
    the row after a failed claim, so the loser must report the winner's
    committed value: `now + cooldown_seconds`.
    """
    conn = fresh_test_conn()
    user_id, acct, _key = TableWrite.create_user(
        conn, email="thread-race@example.com", password_hash="x", handle=None
    )
    conn.close()

    lock = threading.Lock()
    mints: list[tuple[str, int]] = []
    results: list = []
    barrier = threading.Barrier(2)

    class _SlowFakeOnchain:
        def usd_balance(self, address: str) -> int:
            return 30_000_000_000  # below target, same value for both threads

        def mint_to(self, recipient: str, amount_raw: int, *, timeout: int = 30):
            time.sleep(0.05)  # keep the unlocked window open long enough to collide
            with lock:
                mints.append((recipient, amount_raw))

    db = fresh_test_db()
    onchain = _SlowFakeOnchain()
    service = BalanceService(db, onchain, Settings(), _NoPositions())
    user = _User(user_id, acct.address)
    now = 1_700_000_000

    def worker():
        barrier.wait()
        result = service.top_up(user, now)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(mints) == 1

    assert len(results) == 2
    losers = [r for r in results if r.minted_raw == 0]
    assert len(losers) == 1
    assert losers[0].next_allowed_at == now + DAY
    db.close()


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
