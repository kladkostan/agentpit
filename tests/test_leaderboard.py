from agentpit.config import Settings
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.leaderboard_service import LeaderboardService
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


def test_maker_only_trade_still_counts_as_traded():
    """The membership OR must check both api-key columns. All the other
    fixtures here only ever populate TAKER_API_KEY, so on its own a query
    that quietly narrowed to taker-only would still pass the whole suite."""
    conn = fresh_test_conn()
    maker_id, _maker_acct, maker_key = TableWrite.create_user(
        conn, email="maker@example.com", password_hash="x", handle=None
    )
    _taker_id, _taker_acct, taker_key = TableWrite.create_user(
        conn, email="taker@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s, %s)",
        ("t4", taker_key, maker_key, 1_700_000_000),
    )

    ids = {r.user_id for r in TableRead.list_traded_accounts(conn)}
    assert maker_id in ids
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


def test_latest_snapshot_breaks_a_tied_t_by_insertion_order():
    """A retried or duplicated pass can stamp two rows for the same account
    with the same T; SNAPSHOT_ID DESC keeps the winner deterministic -- the
    most recently written row -- instead of leaving it up to plan shape."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="tie@example.com", password_hash="x", handle=None
    )
    TableWrite.insert_account_snapshot(conn, user_id, 5_000, 111, 222)
    TableWrite.insert_account_snapshot(conn, user_id, 5_000, 999, 888)

    latest = TableRead.latest_account_snapshots(conn)
    assert latest[user_id] == (999, 888)
    conn.close()


# ----- LeaderboardService: orchestration and the money arithmetic ----------


class _FakeOnchainBalance:
    """usd_balance keyed by address; unknown addresses read as `default`."""

    def __init__(self, balances: dict[str, int] | None = None, default: int = 0):
        self._balances = balances or {}
        self._default = default

    def usd_balance(self, address: str) -> int:
        return self._balances.get(address, self._default)


class _FakeAccounts:
    """total_value keyed by address; an address with no positions -- or one
    never given a value -- reads back as [] like AccountService.total_value
    does for an account holding nothing."""

    def __init__(self, values: dict[str, float] | None = None):
        self._values = values or {}

    def total_value(self, address: str) -> list[dict]:
        if address not in self._values:
            return []
        return [{"user": address, "value": self._values[address]}]


def test_capital_raw_sums_cash_and_position_value():
    onchain = _FakeOnchainBalance({"0xabc": 30_000_000_000})
    accounts = _FakeAccounts({"0xabc": 70_000.0})
    service = LeaderboardService(
        db=None, onchain=onchain, accounts=accounts, settings=Settings()
    )
    assert service._capital_raw("0xabc") == 100_000_000_000


def test_capital_raw_with_no_positions_is_just_cash():
    onchain = _FakeOnchainBalance({"0xabc": 42_000_000})
    accounts = _FakeAccounts()  # no address has ever been valued
    service = LeaderboardService(
        db=None, onchain=onchain, accounts=accounts, settings=Settings()
    )
    assert service._capital_raw("0xabc") == 42_000_000


def test_take_snapshot_writes_one_row_per_traded_account_with_deposited():
    conn = fresh_test_conn()
    user_id, acct, key = TableWrite.create_user(
        conn, email="valued@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t5", key, 1_700_000_000),
    )
    TableWrite.set_total_deposited(conn, user_id, 55_000_000_000)
    conn.close()

    db = fresh_test_db()
    onchain = _FakeOnchainBalance({acct.address: 30_000_000_000})
    accounts = _FakeAccounts({acct.address: 70_000.0})
    service = LeaderboardService(db, onchain, accounts, Settings())

    written = service.take_snapshot(1_700_001_000)
    assert written == 1

    check = fresh_test_conn()
    latest = TableRead.latest_account_snapshots(check)
    check.close()
    assert latest[user_id] == (100_000_000_000, 55_000_000_000)
    db.close()


def test_one_account_write_failure_does_not_cost_the_rest(monkeypatch):
    """The per-account guard must cover the write, not just the on-chain
    read. Patch insert_account_snapshot to blow up for exactly one of two
    traded accounts and confirm the other still gets its row -- and that
    take_snapshot reports 1 rather than raising out of the whole pass."""
    conn = fresh_test_conn()
    bad_id, bad_acct, bad_key = TableWrite.create_user(
        conn, email="bad@example.com", password_hash="x", handle=None
    )
    good_id, good_acct, good_key = TableWrite.create_user(
        conn, email="good@example.com", password_hash="x", handle=None
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-bad", bad_key, 1_700_000_000),
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-good", good_key, 1_700_000_100),
    )
    conn.close()

    real_insert = TableWrite.insert_account_snapshot

    def flaky_insert(db, user_id, t, capital_raw, deposited_raw):
        if user_id == bad_id:
            raise RuntimeError("db hiccup on insert")
        return real_insert(db, user_id, t, capital_raw, deposited_raw)

    monkeypatch.setattr(TableWrite, "insert_account_snapshot", flaky_insert)

    db = fresh_test_db()
    onchain = _FakeOnchainBalance({bad_acct.address: 0, good_acct.address: 0})
    accounts = _FakeAccounts()
    service = LeaderboardService(db, onchain, accounts, Settings())

    written = service.take_snapshot(1_700_002_000)
    assert written == 1

    check = fresh_test_conn()
    latest = TableRead.latest_account_snapshots(check)
    check.close()
    assert good_id in latest
    assert bad_id not in latest
    db.close()


from agentpit.services.leaderboard_service import (
    SORTS,
    LeaderboardRow,
    display_name,
    rank_rows,
)


def _row(
    name, capital, deposited, trades=1, is_house_agent=False, address="0x" + "11" * 20
):
    return LeaderboardRow(
        name=name,
        address=address,
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


def test_ties_break_deterministically_by_address():
    """`list_traded_accounts` has no guaranteed row order of its own (a plain
    `SELECT DISTINCT`), so two accounts tied on every ranking figure could
    otherwise flip position between two cache refreshes with no change in the
    underlying data. Feeding rank_rows the same two rows in both orders must
    still produce the same output order."""
    a = _row(
        "a", capital=100_000_000_000, deposited=100_000_000_000, trades=3,
        address="0x" + "aa" * 20,
    )
    b = _row(
        "b", capital=100_000_000_000, deposited=100_000_000_000, trades=3,
        address="0x" + "bb" * 20,
    )
    for sort in SORTS:
        first = [r.address for r in rank_rows([a, b], sort)]
        second = [r.address for r in rank_rows([b, a], sort)]
        assert first == second, f"sort={sort} was not deterministic"


def test_build_board_flags_house_agents_by_handle():
    """The five Arena personalities are marked by matching
    Settings.house_agent_handles against the account's handle -- a wrong
    settings field or a case mismatch would otherwise pass the rest of the
    suite untouched, since the only other is_house_agent test passes the bool
    straight into LeaderboardRow without going through build_board at all."""
    conn = fresh_test_conn()
    house_id, house_acct, house_key = TableWrite.create_user(
        conn, email="house-agent@example.com", password_hash="x", handle="bold"
    )
    other_id, other_acct, other_key = TableWrite.create_user(
        conn, email="not-house@example.com", password_hash="x", handle="not_house"
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-house", house_key, 1_700_000_000),
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, TAKER_API_KEY, MATCH_TIME) "
        "VALUES (%s, %s, %s)",
        ("t-other", other_key, 1_700_000_100),
    )
    TableWrite.insert_account_snapshot(conn, house_id, 1_800_000_000, 10, 10)
    TableWrite.insert_account_snapshot(conn, other_id, 1_800_000_000, 10, 10)
    conn.close()

    db = fresh_test_db()
    # onchain/accounts are never touched by build_board -- passing None proves
    # it, the same way the endpoint-level test proves it with raising fakes.
    service = LeaderboardService(db, onchain=None, accounts=None, settings=Settings())
    flagged = {row.address: row.is_house_agent for row in service.build_board()}
    db.close()

    assert flagged[house_acct.address] is True
    assert flagged[other_acct.address] is False
