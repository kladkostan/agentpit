"""Taking the key to a wallet that is yours.

agentpit generates the wallet and holds its key. Export is what lets the
account holder put it in MetaMask and fund it. The dangerous path is a code
that proves somebody's identity, not necessarily THIS account's.

Two separate things close it, and it is worth not confusing them. WorkOS pairs
a code with the address it was mailed to, and `export_private_key` always asks
about the row's OWN address -- so a code mailed elsewhere is refused by that
pairing, as a 401, before anything of ours looks at it. The `workos_user_id`
pin in `AuthService.export_private_key` covers what the pairing cannot: a stale
`users.EMAIL`, where the address has changed hands upstream and a genuine code
for it now belongs to a different WorkOS identity. See
`test_a_code_belonging_to_a_different_account_is_refused` and
`test_a_stale_email_pins_to_the_row_s_own_identity` below.

Anvil + the deployed exchange must be running -- signing in with a mailed code
runs the same on-chain onboarding every other auth test relies on.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from agentpit.api import deps
from agentpit.api.main import app
from agentpit.auth.dependencies import make_current_user_dep
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

    Scoped to this file only, not the root conftest: swapping in
    `_FakeAuthKitVerifier` changes nothing for the X-API-Key path (checked
    first, unaffected), but every test file that does not ask for it relies on
    the root conftest's default -- built once with a resolver that
    deliberately raises on any use (see its docstring) -- to catch a real
    network fetch by accident. Restoring that default afterward, rather than
    popping the override, matches `_using` above for the same reason: the root
    conftest's is not the original value either, and popping would delete it
    for every test that runs after this one.

    `tests/api/conftest.py` pairs the same verifier with a WorkOS double as an
    opt-in `workos` fixture, for the files that only need "an account that is
    signed in". This file keeps its own copy because it shadows that fixture
    name with its own and signs in by hand, and because autouse covers the
    tests here that drive a bearer request without asking for a double.
    """
    previous = app.dependency_overrides.get(deps.get_current_user)
    app.dependency_overrides[deps.get_current_user] = make_current_user_dep(
        _FakeAuthKitVerifier()
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


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


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
    # NOT a test of the workos_user_id pin -- `export_private_key` calls
    # `authenticate_with_code(user.email, code)` with THIS account's own
    # (correct) email, so a code mailed to a different address is refused by
    # the email/code pairing itself (WorkOsError -> 401, same as a wrong
    # digit), before the pin is ever reached. Real WorkOS enforces that
    # pairing the same way `FakeWorkOsClient` does. What this proves is that
    # protection: presenting a genuinely-mailed, currently-valid code for the
    # wrong account does not work. See
    # `test_a_stale_email_pins_to_the_row_s_own_identity` below for the pin
    # itself -- the case this one cannot reach.
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


def test_a_stale_email_pins_to_the_row_s_own_identity(workos, db_conn):
    """The pin's actual job, per its own comment in `auth_service.py`: a
    stale `users.EMAIL` -- the address changed hands upstream, so the row's
    stored email no longer belongs to the identity `WORKOS_USER_ID` names.

    Reproduced directly rather than via a second account signing in (EMAIL is
    UNIQUE, so two rows could never share one anyway): repoint this row's
    EMAIL at an address with its OWN distinct WorkOS identity, while leaving
    WORKOS_USER_ID untouched. The code that gets mailed now proves that
    OTHER identity, not the one signed in here -- exactly the gap
    `authenticate_with_code`'s email/code pairing (see the test above) cannot
    close, because the service still calls it with the row's own email and
    that call still succeeds.

    Confirmed this fails with the pin (the `session.workos_user_id !=
    user.workos_user_id` check in `export_private_key`) commented out: the
    export then returns 200 instead of 401 -- see the task report.
    """
    with TestClient(app) as client:
        session = _sign_in(client, workos, "victim@example.com")
        user_id = session["user"]["user_id"]

        db_conn.execute(
            "UPDATE users SET EMAIL = %s WHERE USER_ID = %s",
            ("stranger@example.com", user_id),
        )

        assert client.post(
            "/me/private-key/code", headers=_auth(session)
        ).status_code == 202
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("stranger@example.com")},
            headers=_auth(session),
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


def test_a_failed_attempt_still_starts_the_cooldown(workos):
    # The regression the cooldown block's own long comment in `auth_service.py`
    # exists to prevent: every failure branch used to raise INSIDE the same
    # transaction as the attempt stamp, so psycopg rolled the stamp back along
    # with the exception and a REJECTED guess cost nothing. A wrong code, then
    # the RIGHT one immediately after, must still be refused by the cooldown
    # the first (failed) attempt opened -- or an attacker can guess at full
    # speed while only the legitimate owner ever waits. `test_the_cooldown_
    # still_applies` above is `success` -> retry, not this: a first attempt
    # that succeeds proves nothing about whether a REJECTED one still stamps,
    # because a working implementation and one that rolls the stamp back on
    # failure look identical when the first attempt never fails.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "guess@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        correct_code = workos.last_code("guess@example.com")

        wrong = client.post(
            "/me/private-key", json={"code": "000000"}, headers=_auth(session)
        )
        assert wrong.status_code == 401, wrong.text

        resp = client.post(
            "/me/private-key", json={"code": correct_code}, headers=_auth(session)
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
    # A legacy row that has never been through WorkOS has a null
    # WORKOS_USER_ID, so there is nothing to pin a code against.
    #
    # The cutover did NOT close this branch, contrary to what the note here
    # used to say: it reaches `current_user` by `X-API-Key`, which is checked
    # ahead of every token path and did not move to WorkOS. A bot holding a
    # key issued before the migration is exactly this case, so the row is
    # built directly rather than signed in -- there is no HTTP door left that
    # makes one.
    with fresh_test_conn() as conn:
        _user_id, _acct, api_key = TableWrite.create_user(
            conn, email="legacy@example.com", password_hash="$2b$12$x", handle=None
        )
    with TestClient(app) as client:
        resp = client.post(
            "/me/private-key",
            json={"code": "123456"},
            headers={"X-API-Key": api_key},
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


def test_a_503_export_does_not_spend_the_cooldown(workos):
    # `export_private_key` checks configuration BEFORE claiming the cooldown.
    # Claiming first meant every 503 burned the 5-second window without
    # verifying anything, so the first real attempt after WorkOS was configured
    # met "too many attempts" -- a guessing floor charged for a feature that
    # was switched off.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "cooldown503@example.com")
        app.dependency_overrides[deps.get_workos_client] = lambda: None
        try:
            refused = client.post(
                "/me/private-key", json={"code": "123456"}, headers=_auth(session)
            )
        finally:
            app.dependency_overrides[deps.get_workos_client] = lambda: workos
        assert refused.status_code == 503, refused.text

        # Immediately after, comfortably inside KEY_EXPORT_COOLDOWN_S.
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("cooldown503@example.com")},
            headers=_auth(session),
        )
    assert resp.status_code == 200, resp.text


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


def test_the_key_is_absent_from_every_other_response(client, workos):
    """UserPublic is a whitelist and must stay one."""
    session = _sign_in(client, workos, "whitelist@example.com")
    r = client.get("/me", headers=_auth(session))
    assert r.status_code == 200
    assert "private_key" not in r.text
    assert "eth_key" not in r.text


def test_has_password_reflects_whether_the_row_still_carries_a_hash(client):
    """`has_password` still has to tell the truth about both kinds of row.

    Nothing signing in today sets a hash, so both rows are built directly and
    read back over `X-API-Key`: the only door left that a row with no WorkOS
    identity can come through. `change_password` is the last live reader of
    the distinction, and it goes with the column in plan 4 -- until then the
    field must not start reporting True for the accounts the cutover creates,
    which would put a password form in front of people who have never had one.
    """
    with fresh_test_conn() as conn:
        _uid, _acct, with_hash = TableWrite.create_user(
            conn, email="haspw@example.com", password_hash="$2b$12$x", handle=None
        )
        _uid2, _acct2, without_hash = TableWrite.create_user(
            conn, email="nopw@example.com", password_hash=None, handle=None
        )

    legacy = client.get("/me", headers={"X-API-Key": with_hash}).json()
    current = client.get("/me", headers={"X-API-Key": without_hash}).json()
    assert legacy["has_password"] is True
    assert current["has_password"] is False


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
