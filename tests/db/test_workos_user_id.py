from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def test_set_and_read_back():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="w@example.com", password_hash="$2b$12$x", handle=None
        )
        assert TableRead.get_user_by_workos_id(conn, "user_01") is None
        assert TableWrite.set_workos_user_id(conn, user_id, "user_01") is True

    with db.read() as conn:
        found = TableRead.get_user_by_workos_id(conn, "user_01")
    assert found is not None
    assert found.user_id == user_id


def test_set_on_a_missing_row_reports_false():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        assert TableWrite.set_workos_user_id(conn, "nope", "user_02") is False


def test_lookup_is_exact_not_fuzzy():
    # A WorkOS id is an opaque token, not an address: it must match exactly or
    # not at all. A LIKE or case-folded lookup here would let one identity
    # answer for another.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="x@example.com", password_hash=None, handle=None
        )
        TableWrite.set_workos_user_id(conn, user_id, "user_ABC")

    with db.read() as conn:
        assert TableRead.get_user_by_workos_id(conn, "user_abc") is None
        assert TableRead.get_user_by_workos_id(conn, "user_ABC") is not None
