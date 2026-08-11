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
    # The sign-in writer, unlike the migration one above. It stamps the
    # identity and LEAVES THE PASSWORD ALONE.
    #
    # Clearing it is the eventual intent -- registration takes any address on
    # trust while a mailed code proves it -- but `export_private_key` chooses
    # its second factor by what the account has: a hash means "prove the
    # password", no hash means "prove the Google identity". Nulling the hash on
    # a password account leaves neither branch satisfiable, so the holder can
    # never export their own key again, and the hash is gone for good. All 17
    # production accounts are that shape. The replacement factor (re-auth by
    # mailed code) lands in plan 3 together with dropping the column.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="link@example.com", password_hash="$2b$12$x", handle=None
        )
        assert TableWrite.link_workos_identity(conn, user_id, "user_linked") is True

    with db.read() as conn:
        found = TableRead.get_user_by_workos_id(conn, "user_linked")
        assert found is not None and found.user_id == user_id
        assert TableRead.get_password_hash_by_userid(conn, user_id) == "$2b$12$x"


def test_adoption_leaves_key_export_reachable():
    """The consequence the invariant above exists for, asserted end to end.

    `export_private_key` branches on the presence of a hash. If adoption
    removed it from a non-Google account, both branches would refuse and the
    wallet's own key would be permanently unreachable.
    """
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="export@example.com", password_hash="$2b$12$y", handle=None
        )
        TableWrite.link_workos_identity(conn, user_id, "user_export")

    with db.read() as conn:
        user = TableRead.get_user_by_workos_id(conn, "user_export")
        assert user is not None
        # Truthy `has_password` is what routes the export to the password
        # factor; false on an account with no GOOGLE_SUB is the dead end.
        assert user.has_password is True


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
