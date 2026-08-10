"""Taking the key to a wallet that is yours.

agentpit generates the wallet and holds its key. Export is what lets the
account holder put it in MetaMask and fund it. The dangerous path is the
Google one: a valid token proves somebody signed in, not that THIS account's
owner did.

Anvil + the deployed exchange must be running — registering (by password or
Google) runs the same on-chain onboarding every other auth test relies on.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_google_verifier
from agentpit.api.main import app
from agentpit.auth.google import GoogleIdentity, GoogleTokenVerifier
from agentpit.auth.jwt import JwtCoder
from agentpit.config import Settings
from agentpit.db.row_factory import ci_dict_row
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.auth_service import AuthService
from tests.db_helpers import TEST_DSN, fresh_test_conn, fresh_test_db


@dataclass
class _RegisteredUser:
    user_id: str
    password: str
    eth_address: str
    auth_header: dict


@dataclass
class _GoogleUser:
    user_id: str
    google_sub: str
    email: str
    eth_address: str
    auth_header: dict


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def registered_user(client) -> _RegisteredUser:
    password = "hunter22hunter22"
    body = client.post(
        "/register",
        json={"email": "keyexport@example.com", "password": password},
    ).json()
    return _RegisteredUser(
        user_id=body["user"]["user_id"],
        password=password,
        eth_address=body["user"]["eth_address"],
        auth_header={"Authorization": f"Bearer {body['access_token']}"},
    )


@pytest.fixture
def google_user(client):
    """A signed-in Google account, verified through a real `GoogleTokenVerifier`
    instance (installed as the app's dependency for the life of this fixture)
    rather than the `_StubVerifier` the other Google tests use — patching
    `GoogleTokenVerifier.verify` at the class level, as the dangerous-path test
    below needs to, only intercepts calls made through a real instance.
    """
    previous = app.dependency_overrides.get(get_google_verifier)
    app.dependency_overrides[get_google_verifier] = lambda: GoogleTokenVerifier(
        "test-client-id"
    )
    try:
        sub = "google-sub-key-export-owner"
        email = "keyexport-google@example.com"
        with patch(
            "agentpit.auth.google.GoogleTokenVerifier.verify",
            return_value=GoogleIdentity(sub=sub, email=email),
        ):
            body = client.post("/auth/google", json={"credential": "cred-owner"}).json()
        yield _GoogleUser(
            user_id=body["user"]["user_id"],
            google_sub=sub,
            email=email,
            eth_address=body["user"]["eth_address"],
            auth_header={"Authorization": f"Bearer {body['access_token']}"},
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_google_verifier, None)
        else:
            app.dependency_overrides[get_google_verifier] = previous


@pytest.fixture
def other_google_sub() -> str:
    """A Google `sub` that belongs to nobody in this account's row."""
    return "google-sub-someone-else"


@pytest.fixture
def db_conn():
    conn = fresh_test_conn()
    yield conn
    conn.close()


def test_a_password_account_exports_with_its_password(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["private_key"].startswith("0x")
    assert len(body["private_key"]) == 66
    assert body["eth_address"] == registered_user.eth_address


def test_a_wrong_password_is_rejected(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": "not-the-password"},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 401
    assert "private_key" not in r.text


def test_a_password_account_cannot_use_the_google_door(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"google_credential": "anything"},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 400
    assert "private_key" not in r.text


def test_a_google_token_for_a_DIFFERENT_account_gets_nothing(
    client, google_user, other_google_sub
):
    """The one that matters. A valid Google token proves somebody signed in;
    it must also be THIS account's identity, or the key goes to whoever
    authenticated last."""
    with patch(
        "agentpit.auth.google.GoogleTokenVerifier.verify",
        return_value=GoogleIdentity(sub=other_google_sub, email="someone@else.com"),
    ):
        r = client.post(
            "/me/private-key",
            json={"google_credential": "a-valid-token-for-someone-else"},
            headers=google_user.auth_header,
        )
    assert r.status_code == 401
    assert "private_key" not in r.text


def test_a_google_account_exports_with_its_own_token(client, google_user):
    with patch(
        "agentpit.auth.google.GoogleTokenVerifier.verify",
        return_value=GoogleIdentity(sub=google_user.google_sub, email=google_user.email),
    ):
        r = client.post(
            "/me/private-key",
            json={"google_credential": "a-valid-token"},
            headers=google_user.auth_header,
        )
    assert r.status_code == 200
    assert r.json()["private_key"].startswith("0x")


def test_the_key_is_absent_from_every_other_response(client, registered_user):
    """UserPublic is a whitelist and must stay one."""
    r = client.get("/me", headers=registered_user.auth_header)
    assert r.status_code == 200
    assert "private_key" not in r.text
    assert "eth_key" not in r.text


def test_a_successful_export_is_stamped(client, registered_user, db_conn):
    client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    row = db_conn.execute(
        "SELECT KEY_EXPORTED_AT FROM users WHERE USER_ID = %s",
        (registered_user.user_id,),
    ).fetchone()
    assert row["KEY_EXPORTED_AT"] is not None


def test_the_response_is_not_cacheable(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    assert r.headers.get("cache-control") == "no-store"


def test_has_password_reflects_how_the_account_signs_in(
    client, registered_user, google_user
):
    """The Task 2 dialog needs to know which factor to show without guessing
    client-side, so `UserPublic.has_password` has to tell the truth for both
    kinds of account."""
    password_account = client.get("/me", headers=registered_user.auth_header).json()
    google_account = client.get("/me", headers=google_user.auth_header).json()
    assert password_account["has_password"] is True
    assert google_account["has_password"] is False


# ----- security invariants ---------------------------------------------


def test_a_failed_attempt_still_starts_the_cooldown(client, registered_user):
    """The regression this closes: every failure branch used to raise inside
    the same transaction as the attempt stamp, so psycopg rolled the stamp
    back along with the exception and a REJECTED guess cost nothing. A second
    call right after -- even with the RIGHT password this time -- must still
    be refused while the window from the first (failed) attempt is open, or
    an attacker can guess at full speed while only the legitimate owner ever
    waits."""
    first = client.post(
        "/me/private-key",
        json={"password": "not-the-password"},
        headers=registered_user.auth_header,
    )
    assert first.status_code == 401

    second = client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    assert second.status_code == 400
    assert "private_key" not in second.text


def test_mark_key_exported_stamps_only_the_first_export(db_conn):
    """The re-grant lock in `_maybe_reonboard` reads this column; if a second
    export moved the stamp, the lock would look like it lapses every time the
    key is exported again."""
    user_id, _acct, _key = TableWrite.create_user(
        db_conn, email="stampfirst@example.com", password_hash="x", handle=None
    )
    assert TableWrite.mark_key_exported(db_conn, user_id, 1_000) is True
    assert TableWrite.mark_key_exported(db_conn, user_id, 2_000) is False

    exported_at, _ = TableRead.get_key_export_state(db_conn, user_id)
    assert exported_at == 1_000


def test_a_second_claim_blocked_on_the_row_lock_sees_the_first_and_loses():
    """`mark_key_export_attempt`'s predicate and its stamp are one UPDATE so
    a concurrent caller cannot read the pre-claim timestamp and pass the
    check too. This does not hope two threads happen to collide -- it forces
    the exact interleaving: connection A claims the attempt and is held open
    (uncommitted) on purpose; a second thread's claim on connection B is
    issued while A is still open and must block on A's row lock rather than
    read around it. Only once A commits does B's UPDATE get to run, and by
    then it is re-checking its WHERE clause against A's just-committed
    stamp -- READ COMMITTED re-evaluates the predicate against the newest
    committed row, not the row B's transaction originally saw. That is what
    makes B lose even though its own read (if it had done a separate one)
    would have raced cleanly."""
    setup = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        setup, email="export-race@example.com", password_hash="x", handle=None
    )
    setup.close()

    cooldown = 5
    t1 = 1_700_000_000
    t2 = t1 + 1  # inside the cooldown window opened by t1

    conn_a = psycopg.connect(TEST_DSN, autocommit=False, row_factory=ci_dict_row)
    conn_b = psycopg.connect(TEST_DSN, autocommit=False, row_factory=ci_dict_row)
    try:
        claimed_a = TableWrite.mark_key_export_attempt(
            conn_a, user_id, t1, t1 - cooldown
        )
        assert claimed_a is True  # no prior attempt -- the IS NULL branch
        # conn_a's transaction is deliberately left open (uncommitted): its
        # row lock on this user is what forces B to block below rather than
        # racing a stale read.

        result_b: list[bool] = []

        def claim_b() -> None:
            result_b.append(
                TableWrite.mark_key_export_attempt(
                    conn_b, user_id, t2, t2 - cooldown
                )
            )
            conn_b.commit()

        b_thread = threading.Thread(target=claim_b)
        b_thread.start()
        b_thread.join(timeout=1)
        assert b_thread.is_alive(), (
            "B must still be blocked on A's row lock -- if it already "
            "finished, this test proved nothing about the race"
        )

        conn_a.commit()  # releases the lock; B's UPDATE can now proceed
        b_thread.join(timeout=5)
        assert not b_thread.is_alive()

        assert result_b == [False], "B must see A's committed stamp and lose"

        check = fresh_test_conn()
        row = check.execute(
            "SELECT KEY_EXPORT_ATTEMPT_AT FROM users WHERE USER_ID = %s",
            (user_id,),
        ).fetchone()
        check.close()
        assert row["KEY_EXPORT_ATTEMPT_AT"] == t1, (
            "B's losing claim must not have overwritten A's stamp"
        )
    finally:
        conn_a.close()
        conn_b.close()


class _NeverCalledOnchain:
    """Every method records that it ran. `_maybe_reonboard`'s export-lock
    guard must return before touching the chain at all, so the assertion is
    that none of these lists ever gain an entry."""

    def __init__(self):
        self.fund_gas_calls: list = []

    def fund_gas(self, *args, **kwargs):
        self.fund_gas_calls.append((args, kwargs))

    def faucet_drip(self, *args, **kwargs):
        raise AssertionError("faucet_drip ran after the key was exported")

    def grant_user_approvals(self, *args, **kwargs):
        raise AssertionError("grant_user_approvals ran after the key was exported")

    def native_balance(self, *args, **kwargs):
        raise AssertionError("native_balance ran after the key was exported")


def test_the_re_grant_lock_stops_reonboarding_once_the_key_is_exported():
    """`_maybe_reonboard` re-funds an account it believes was wiped by a chain
    reset. Once the holder has the key, a zero balance can also mean they
    emptied it on purpose -- so once `KEY_EXPORTED_AT` is set, this must
    return without ever reading the chain, let alone re-funding it."""
    db = fresh_test_db()
    try:
        settings = Settings()
        service = AuthService(db, JwtCoder(settings), _NeverCalledOnchain(), settings)
        onchain = service._onchain

        with db.write() as conn:
            user_id, _acct, _key = TableWrite.create_user(
                conn, email="regrantlock@example.com", password_hash="x", handle=None
            )
            TableWrite.mark_user_onboarded(conn, user_id)
            TableWrite.mark_key_exported(conn, user_id, 1_700_000_000)

        with db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)

        service._maybe_reonboard(user)

        assert onchain.fund_gas_calls == []
    finally:
        db.close()
