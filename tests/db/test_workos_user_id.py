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


def test_the_migration_writer_leaves_the_password_alone():
    # The migration backfills ids for accounts nobody has signed into yet, and
    # those accounts must keep logging in with their password until plan 3
    # takes that door away.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="keep@example.com", password_hash="$2b$12$x", handle=None
        )
        TableWrite.set_workos_user_id(conn, user_id, "user_keep")

    with db.read() as conn:
        assert TableRead.get_password_hash_by_userid(conn, user_id) == "$2b$12$x"


def test_linking_stamps_the_identity_and_drops_the_password():
    # The sign-in writer, unlike the migration one above. Registration takes
    # any address on trust, so the password on the row is no evidence that
    # whoever set it owns the address -- the mailed code is. Leaving the hash
    # would keep /login (and, through it, the key export that gates on having
    # a password) working for whoever registered a stranger's address.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="link@example.com", password_hash="$2b$12$x", handle=None
        )
        assert TableWrite.link_workos_identity(conn, user_id, "user_linked") is True

    with db.read() as conn:
        found = TableRead.get_user_by_workos_id(conn, "user_linked")
        assert found is not None and found.user_id == user_id
        assert TableRead.get_password_hash_by_userid(conn, user_id) is None


def test_linking_a_missing_row_reports_false():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        assert TableWrite.link_workos_identity(conn, "nope", "user_03") is False


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
