"""Taking the key to a wallet that is yours.

agentpit generates the wallet and holds its key. Export is what lets the
account holder put it in MetaMask and fund it. The dangerous path is a code
that proves somebody's identity, not necessarily THIS account's -- the
`workos_user_id` pin in `AuthService.export_private_key` is what keeps a code
genuinely mailed to one account from unlocking another's key.

Anvil + the deployed exchange must be running -- registering (by password) or
signing in with a mailed code runs the same on-chain onboarding every other
auth test relies on.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from agentpit.api import deps
from agentpit.api.deps import get_google_verifier
from agentpit.api.main import app
from agentpit.auth.dependencies import make_current_user_dep
from agentpit.auth.google import GoogleIdentity, GoogleTokenVerifier
from agentpit.auth.jwt import JwtCoder
from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.config import Settings
from agentpit.db.row_factory import ci_dict_row
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import InvalidCredentialsError
from agentpit.services.auth_service import AuthService
from tests.db_helpers import TEST_DSN, fresh_test_conn, fresh_test_db


@contextmanager
def _using(client):
    """Swap the app's WorkOS client, then put back exactly what was there.

    Copied from `tests/api/test_authkit_routes.py` rather than imported: see
    that module's copy of this helper for why restoring beats popping --
    conftest's shared fake sits under this same key, and popping would delete
    it for every test that runs after this one in the session.
    """
    previous = app.dependency_overrides.get(deps.get_workos_client)
    app.dependency_overrides[deps.get_workos_client] = lambda: client
    try:
        yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(deps.get_workos_client, None)
        else:
            app.dependency_overrides[deps.get_workos_client] = previous


@pytest.fixture
def workos():
    with _using(FakeWorkOsClient()) as fake:
        yield fake


class _FakeAuthKitVerifier:
    """Maps `FakeWorkOsClient`'s access token straight back to its
    `workos_user_id`, instead of verifying a signature.

    Every export test in this file signs in over HTTP and then re-presents
    that session's access token as a bearer credential on a LATER request --
    export re-authenticates a second call on the same signed-in account, which
    nothing before this file needed. The production `AuthKitVerifier` checks a
    real JWT's signature, issuer and `client_id` claim against a JWKS fetched
    over the network -- exactly what a unit test may never do, and not
    something `FakeWorkOsClient` attempts either: it mints an opaque
    `at-<workos_user_id>` string (see `workos_client.py`), which is precise
    enough for every test that only inspects the `/auth/session` response
    itself. `AuthKitVerifier.verify`'s contract is "token in, workos_user_id
    out"; this satisfies exactly that without pretending to check a signature
    the double never produced.
    """

    def verify(self, token: str) -> str:
        if not token.startswith("at-"):
            raise InvalidCredentialsError("invalid session")
        return token[3:]


@pytest.fixture(autouse=True)
def _fake_authkit_bearer():
    """Let a `FakeWorkOsClient` session authenticate a second request.

    Scoped to this file only, not conftest: swapping in `_FakeAuthKitVerifier`
    changes nothing for the X-API-Key or legacy-JWT paths (checked first,
    unaffected), but every OTHER test file relies on conftest's default --
    built once with a resolver that deliberately raises on any use (see its
    docstring) -- to catch a real network fetch by accident. Restoring that
    default afterward, rather than popping the override, matches `_using`
    above for the same reason: conftest's is not the original value either,
    and popping would delete it for every test that runs after this one.
    """
    previous = app.dependency_overrides.get(deps.get_current_user)
    app.dependency_overrides[deps.get_current_user] = make_current_user_dep(
        app.dependency_overrides[deps.get_jwt_coder](), _FakeAuthKitVerifier()
    )
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(deps.get_current_user, None)
        else:
            app.dependency_overrides[deps.get_current_user] = previous


def _sign_in(client, workos, email: str) -> dict:
    """A signed-in account, the only way there is one now: address, code, in."""
    client.post("/auth/code", json={"email": email})
    resp = client.post(
        "/auth/session", json={"email": email, "code": workos.last_code(email)}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


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
    rather than the `_StubVerifier` the other Google tests use -- patching
    `GoogleTokenVerifier.verify` at the class level, as `has_password` below
    needs to, only intercepts calls made through a real instance.
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
def db_conn():
    conn = fresh_test_conn()
    yield conn
    conn.close()


# ----- the mailed-code factor -------------------------------------------


def test_export_succeeds_with_a_freshly_mailed_code(workos):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "k@example.com")
        assert client.post(
            "/me/private-key/code", headers=_auth(session)
        ).status_code == 202
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("k@example.com")},
            headers=_auth(session),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eth_address"] == session["user"]["eth_address"]
    assert body["private_key"].startswith("0x")


def test_a_code_belonging_to_a_different_account_is_refused(workos):
    # THE test in this task. Without the workos_user_id pin this passes and
    # the key goes to whoever authenticated last.
    with TestClient(app) as client:
        mine = _sign_in(client, workos, "mine@example.com")
        _sign_in(client, workos, "theirs@example.com")
        # A code genuinely mailed to the other account, presented by this one.
        client.post("/auth/code", json={"email": "theirs@example.com"})
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("theirs@example.com")},
            headers=_auth(mine),
        )
    assert resp.status_code == 401, resp.text
    assert "private_key" not in resp.text


def test_a_wrong_code_is_401_and_does_not_stamp_the_export(workos):
    # The stamp matters beyond this endpoint: once EXPORTED_AT is set,
    # `_maybe_reonboard` never repairs that account again. A wrong guess must
    # not spend that.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "w@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key", json={"code": "000000"}, headers=_auth(session)
        )
    assert resp.status_code == 401, resp.text
    with DbSession(Settings().database_url).read() as conn:
        exported_at, _ = TableRead.get_key_export_state(
            conn, session["user"]["user_id"]
        )
    assert exported_at is None


def test_a_malformed_code_is_422_and_never_reaches_workos(workos):
    # Asserted on the call counter, not the status: a local rejection and a
    # round trip both end in a 4xx and are indistinguishable otherwise.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "m@example.com")
        before = workos.authenticate_calls
        resp = client.post(
            "/me/private-key", json={"code": "12345"}, headers=_auth(session)
        )
    assert resp.status_code == 422
    assert workos.authenticate_calls == before


def test_the_cooldown_still_applies(workos):
    # Two attempts inside KEY_EXPORT_COOLDOWN_S. The second is refused before
    # its code is looked at, right or wrong.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "c@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        first_code = workos.last_code("c@example.com")
        assert client.post(
            "/me/private-key", json={"code": first_code}, headers=_auth(session)
        ).status_code == 200
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("c@example.com")},
            headers=_auth(session),
        )
    assert resp.status_code == 400, resp.text
    assert "too many attempts" in resp.text


def test_the_export_code_goes_to_the_account_s_own_address(workos):
    # `/auth/code` takes an address from the request body. This one may only
    # ever mail the address on the row the caller is authenticated as, or the
    # endpoint becomes a way to mail a sign-in code to anybody.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "own@example.com")
        resp = client.post(
            "/me/private-key/code",
            json={"email": "someone-else@example.com"},
            headers=_auth(session),
        )
    assert resp.status_code == 202, resp.text
    assert workos.last_code("own@example.com")
    with pytest.raises(KeyError):
        workos.last_code("someone-else@example.com")


def test_an_account_with_no_workos_identity_is_told_to_sign_in_again(workos):
    # A row from `/register` that has never been through WorkOS has a null
    # WORKOS_USER_ID, so there is nothing to pin a code against. Reachable
    # only while the legacy JWT is still accepted -- Task 8 closes it.
    with TestClient(app) as client:
        made = client.post(
            "/register",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.post(
            "/me/private-key", json={"code": "123456"}, headers=_auth(made)
        )
    assert resp.status_code == 400, resp.text
    assert "sign in again" in resp.text


def test_export_answers_503_when_workos_is_not_configured(workos):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "d@example.com")
        app.dependency_overrides[deps.get_workos_client] = lambda: None
        try:
            resp = client.post("/me/private-key/code", headers=_auth(session))
        finally:
            app.dependency_overrides[deps.get_workos_client] = lambda: workos
    assert resp.status_code == 503, resp.text


# ----- behaviour that doesn't change with the factor ---------------------


def test_a_successful_export_is_stamped(workos, db_conn):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "stamped@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        client.post(
            "/me/private-key",
            json={"code": workos.last_code("stamped@example.com")},
            headers=_auth(session),
        )
    row = db_conn.execute(
        "SELECT KEY_EXPORTED_AT FROM users WHERE USER_ID = %s",
        (session["user"]["user_id"],),
    ).fetchone()
    assert row["KEY_EXPORTED_AT"] is not None


def test_the_response_is_not_cacheable(workos):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "cache@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("cache@example.com")},
            headers=_auth(session),
        )
    assert resp.headers.get("cache-control") == "no-store"


def test_the_key_is_absent_from_every_other_response(client, registered_user):
    """UserPublic is a whitelist and must stay one."""
    r = client.get("/me", headers=registered_user.auth_header)
    assert r.status_code == 200
    assert "private_key" not in r.text
    assert "eth_key" not in r.text


def test_has_password_reflects_how_the_account_signs_in(
    client, registered_user, google_user
):
    """`has_password` still has to tell the truth for both kinds of account:
    `login` uses it to pick "invalid email or password" vs. "this account
    signs in with Google", and `change_password` uses it to refuse a Google
    account outright. Export no longer reads it -- every account now proves
    itself the same way -- but the field itself is not going anywhere."""
    password_account = client.get("/me", headers=registered_user.auth_header).json()
    google_account = client.get("/me", headers=google_user.auth_header).json()
    assert password_account["has_password"] is True
    assert google_account["has_password"] is False


# ----- security invariants ---------------------------------------------


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
