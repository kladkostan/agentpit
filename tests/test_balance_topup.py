from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.balance_service import next_allowed_at, topup_amount_raw
from tests.db_helpers import fresh_test_conn

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
        assert balance + topup_amount_raw(balance, TARGET) <= max(balance, TARGET)


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
