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
