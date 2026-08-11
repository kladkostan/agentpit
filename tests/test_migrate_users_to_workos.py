from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from scripts.migrate_users_to_workos import migrate_users


def _make_user(conn, email, password_hash):
    user_id, _acct, _api_key = TableWrite.create_user(
        conn, email=email, password_hash=password_hash, handle=None
    )
    return user_id


def test_imports_a_password_account_with_its_hash():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        user_id = _make_user(conn, "a@example.com", "$2b$12$realhash")
        report = migrate_users(conn, fake)

    assert report.migrated == 1
    created = fake.find_user_by_email("a@example.com")
    assert created is not None
    with db.read() as conn:
        linked = TableRead.get_user_by_workos_id(conn, created.workos_user_id)
    assert linked is not None and linked.user_id == user_id


def test_a_google_account_without_a_password_still_migrates():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        _make_user(conn, "g@example.com", None)
        report = migrate_users(conn, fake)

    assert report.migrated == 1
    assert fake.find_user_by_email("g@example.com") is not None


def test_running_twice_changes_nothing_the_second_time():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        _make_user(conn, "a@example.com", "$2b$12$realhash")
        first = migrate_users(conn, fake)
    with db.write() as conn:
        second = migrate_users(conn, fake)

    assert first.migrated == 1
    # Already linked, so the second pass has nothing to do -- this is what
    # makes the script safe to re-run after a partial failure.
    assert second.migrated == 0
    assert second.skipped == 1


def test_dry_run_writes_nothing():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        user_id = _make_user(conn, "a@example.com", "$2b$12$realhash")
        report = migrate_users(conn, fake, dry_run=True)

    assert report.migrated == 1  # what it WOULD do
    assert fake.find_user_by_email("a@example.com") is None
    with db.read() as conn:
        assert TableRead.get_user_by_userid(conn, user_id).workos_user_id is None


def test_a_database_error_on_one_row_does_not_poison_the_others():
    """A failing statement aborts the whole Postgres transaction, so the
    per-account `except` has to unwind to a savepoint or it contains nothing.

    The reachable trigger is a pair of case-variant addresses: `users.EMAIL` is
    UNIQUE but case-SENSITIVE, so `grace@` and `Grace@` are two rows here, while
    WorkOS treats an address case-insensitively and hands both the same
    `user_...` id -- which then collides on `idx_users_workos_user_id`. Without
    a savepoint that UniqueViolation is swallowed but the transaction stays
    aborted, so the *next* row dies with InFailedSqlTransaction and the COMMIT
    silently degrades to a ROLLBACK: the report claims success and the database
    has nothing in it.
    """
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        _make_user(conn, "grace@gmail.com", "$2b$12$h")
        _make_user(conn, "Grace@gmail.com", "$2b$12$h")
        zoe_id = _make_user(conn, "zoe@gmail.com", "$2b$12$h")
    with db.write() as conn:
        report = migrate_users(conn, fake)

    assert (report.migrated, report.failed) == (2, 1)
    # The unrelated account is linked, and the link survived the COMMIT.
    with db.read() as conn:
        assert TableRead.get_user_by_userid(conn, zoe_id).workos_user_id is not None
        rows = conn.execute(
            "SELECT EMAIL, WORKOS_USER_ID FROM users ORDER BY EMAIL"
        ).fetchall()
    linked = {r["EMAIL"]: r["WORKOS_USER_ID"] for r in rows}
    # Exactly one of the two case-variants won the shared WorkOS identity; the
    # other is left for a human to merge, which is the honest outcome.
    assert len([e for e in ("grace@gmail.com", "Grace@gmail.com") if linked[e]]) == 1


def test_one_failure_does_not_stop_the_rest():
    class Exploding(FakeWorkOsClient):
        def create_user(self, *, email, password_hash):
            if email == "bad@example.com":
                raise RuntimeError("upstream said no")
            return super().create_user(email=email, password_hash=password_hash)

    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _make_user(conn, "bad@example.com", "$2b$12$h")
        _make_user(conn, "good@example.com", "$2b$12$h")
        report = migrate_users(conn, Exploding())

    # 17 accounts and one bad address must not cost the other 16 their identity.
    assert report.migrated == 1
    assert report.failed == 1
