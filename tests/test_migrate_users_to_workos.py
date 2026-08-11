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
