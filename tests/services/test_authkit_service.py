import pytest

from agentpit.auth.workos_client import FakeWorkOsClient, WorkOsError
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.authkit_service import AuthKitService


class _Onboarder:
    """Stands in for AuthService._onboard_new_account.

    The real one funds gas, drips collateral and sends three approvals -- a
    second or so of chain round-trips. These tests are about identity, so the
    chain is a spy: what matters is that it is called exactly once per NEW
    account and never for a returning one.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, user_id, acct):
        self.calls.append(user_id)
        with DbSession(Settings().database_url).write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)
            return TableRead.get_user_by_userid(conn, user_id)


def _service(workos=None, onboarder=None):
    db = DbSession(Settings().database_url)
    return AuthKitService(
        db=db,
        workos=workos or FakeWorkOsClient(),
        onboard=onboarder or _Onboarder(),
    ), db


def test_first_sign_in_creates_the_account_and_onboards_it():
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)

    svc.send_code("new@example.com")
    session = svc.sign_in("new@example.com", workos.last_code("new@example.com"))

    assert session.user.email == "new@example.com"
    assert session.user.handle  # generated, never blank
    assert session.access_token and session.refresh_token
    assert onboarder.calls == [session.user.user_id]

    with db.read() as conn:
        linked = TableRead.get_user_by_workos_id(
            conn, workos.find_user_by_email("new@example.com").workos_user_id
        )
    assert linked is not None and linked.user_id == session.user.user_id


def test_a_returning_address_lands_on_the_same_row_without_a_second_wallet():
    # The failure this guards is expensive and silent: a second row means a
    # second wallet, a second onboarding paid for on chain, and a person whose
    # positions have vanished.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, _db = _service(workos, onboarder)

    svc.send_code("a@example.com")
    first = svc.sign_in("a@example.com", workos.last_code("a@example.com"))
    svc.send_code("a@example.com")
    second = svc.sign_in("a@example.com", workos.last_code("a@example.com"))

    assert first.user.user_id == second.user.user_id
    assert first.user.eth_address == second.user.eth_address
    assert onboarder.calls == [first.user.user_id]  # onboarded once, not twice


def test_an_account_migrated_by_workos_user_id_is_found_not_recreated():
    # Plan 1's migration script populated WORKOS_USER_ID for the existing
    # accounts. Those people must sign in to their own rows.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    with db.write() as conn:
        user_id, _acct, _key = TableWrite.create_user(
            conn, email="old@example.com", password_hash="$2b$12$x", handle=None
        )
    created = workos.create_user(email="old@example.com", password_hash=None)
    with db.write() as conn:
        TableWrite.set_workos_user_id(conn, user_id, created.workos_user_id)

    workos.send_magic_auth_code("old@example.com")
    session = svc.sign_in("old@example.com", workos.last_code("old@example.com"))

    assert session.user.user_id == user_id
    assert onboarder.calls == []  # already had a wallet


def test_a_wrong_code_creates_nothing():
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    svc.send_code("a@example.com")

    with pytest.raises(WorkOsError):
        svc.sign_in("a@example.com", "000000")

    # The whole point of the design: an address that never answers costs us
    # no row, no wallet and no gas.
    with db.read() as conn:
        assert TableRead.get_user_by_email(conn, "a@example.com") is None
    assert onboarder.calls == []


def test_refresh_returns_the_same_account():
    workos = FakeWorkOsClient()
    svc, _db = _service(workos)
    svc.send_code("a@example.com")
    first = svc.sign_in("a@example.com", workos.last_code("a@example.com"))

    again = svc.refresh(first.refresh_token)
    assert again.user.user_id == first.user.user_id
    assert again.access_token


def test_refresh_for_an_identity_with_no_local_row_is_refused():
    # A valid WorkOS session whose `sub` matches nothing here must not
    # silently mint an account -- account creation belongs to sign_in alone.
    workos = FakeWorkOsClient()
    svc, _db = _service(workos)
    created = workos.create_user(email="ghost@example.com", password_hash=None)
    with pytest.raises(Exception):
        svc.refresh(f"rt-{created.workos_user_id}")
