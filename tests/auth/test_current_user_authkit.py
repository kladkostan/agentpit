"""Three credentials reach `current_user`; this plan may only ADD the third.

`X-API-Key` is every bot trading today, the legacy `JwtCoder` bearer token is
every browser session minted before this plan, and the AuthKit access token is
the new one. The first two have to survive untouched -- plan 3 removes the
second, nothing removes the first.

The dependency is driven directly rather than through the app because the
production key resolver fetches a JWKS over the network on the first token it
sees. Injecting a local resolver, the way `tests/auth/test_authkit_tokens.py`
does, is the only way to exercise this path offline.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from agentpit.auth.authkit_tokens import AuthKitVerifier, authkit_issuer
from agentpit.auth.dependencies import make_current_user_dep
from agentpit.auth.jwt import JwtCoder
from agentpit.config import Settings
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_db

# The client id the token tests use. Every token below carries the claim set
# read off a REAL staging token on 2026-08-11: `iss` derived from the client
# id, a `client_id` claim, and no `aud`.
CLIENT_ID = "client_01KZRZ1QQXA15KX04VQBZPE0DZ"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _authkit_token(*, sub: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": authkit_issuer(CLIENT_ID),
            "sub": sub,
            "sid": "session_01",
            "jti": "01",
            "auth_time": now,
            "client_id": CLIENT_ID,
            "iat": now,
            # Measured, not chosen: an AuthKit access token lives 300 seconds.
            "exp": now + 300,
        },
        _KEY,
        algorithm="RS256",
    )


class _CountingCoder(JwtCoder):
    """The real coder, counting decodes so a test can prove it was NOT called."""

    def __init__(self) -> None:
        super().__init__(Settings())
        self.decodes = 0

    def decode(self, token: str):
        self.decodes += 1
        return super().decode(token)


class _CountingVerifier(AuthKitVerifier):
    """The real verifier over a local key: same contract, no JWKS fetch."""

    def __init__(self) -> None:
        super().__init__(
            client_id=CLIENT_ID, key_resolver=lambda _token: _KEY.public_key()
        )
        self.verifies = 0

    def verify(self, token: str) -> str:
        self.verifies += 1
        return super().verify(token)


@pytest.fixture
def db():
    return fresh_test_db()


@pytest.fixture
def coder() -> _CountingCoder:
    return _CountingCoder()


@pytest.fixture
def verifier() -> _CountingVerifier:
    return _CountingVerifier()


@pytest.fixture
def current_user(coder: _CountingCoder, verifier: _CountingVerifier):
    return make_current_user_dep(coder, verifier)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _make_user(db, *, email: str, workos_user_id: str | None = None):
    """A row, optionally already linked to a WorkOS identity. Returns
    (user_id, api_key)."""
    with db.write() as conn:
        user_id, _acct, api_key = TableWrite.create_user(
            conn, email=email, password_hash="$2b$12$x", handle=None
        )
        if workos_user_id is not None:
            TableWrite.set_workos_user_id(conn, user_id, workos_user_id)
    return user_id, api_key


def _user_count(db) -> int:
    with db.read() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def test_an_api_key_resolves_its_user_without_consulting_either_token_path(
    db, coder, verifier, current_user
):
    # The bot path. Every agent trading today authenticates with this header,
    # and no new test would notice it breaking -- so assert not only that it
    # still works but that it still short-circuits: a refactor that verified
    # the (absent) bearer token first would put a JWKS fetch in front of every
    # order placement.
    user_id, api_key = _make_user(db, email="bot@example.com")

    resolved = current_user(api_key, None, db)

    assert resolved.user_id == user_id
    assert coder.decodes == 0
    assert verifier.verifies == 0


def test_a_bad_api_key_is_401_and_does_not_fall_through_to_the_token_paths(
    db, coder, verifier, current_user
):
    # Same short-circuit, on the failing side: a wrong key must be rejected
    # here, not handed to the verifiers as if it were a bearer token.
    with pytest.raises(HTTPException) as raised:
        current_user("not-a-key", None, db)

    assert raised.value.status_code == 401
    assert coder.decodes == 0
    assert verifier.verifies == 0


def test_a_legacy_bearer_token_still_resolves_its_user(db, verifier, current_user):
    # /register and /login keep minting these until plan 3, and every browser
    # session already open is holding one.
    user_id, _api_key = _make_user(db, email="legacy@example.com")
    token = JwtCoder(Settings()).encode(user_id=user_id, email="legacy@example.com")

    resolved = current_user(None, _bearer(token), db)

    assert resolved.user_id == user_id
    # The legacy check is a local HMAC verification with no I/O and it runs
    # first, so the common case during the transition never pays for the
    # AuthKit path at all.
    assert verifier.verifies == 0


def test_an_authkit_token_resolves_the_row_its_sub_is_linked_to(db, current_user):
    user_id, _api_key = _make_user(
        db, email="new@example.com", workos_user_id="user_authkit_1"
    )

    resolved = current_user(None, _bearer(_authkit_token(sub="user_authkit_1")), db)

    assert resolved.user_id == user_id


def test_an_authkit_token_for_an_unknown_sub_is_401_and_creates_nothing(
    db, current_user
):
    # The token is perfectly valid -- right signature, right application, not
    # expired -- and still must not mint an account. Creation belongs to
    # POST /auth/session alone, which has proof the caller owns the address
    # (the mailed code). Creating here would give any valid AuthKit session
    # for our application a funded wallet by touching any authenticated route.
    before = _user_count(db)

    with pytest.raises(HTTPException) as raised:
        current_user(None, _bearer(_authkit_token(sub="user_nobody")), db)

    assert raised.value.status_code == 401
    assert _user_count(db) == before


def test_a_garbage_bearer_token_is_401(db, current_user):
    with pytest.raises(HTTPException) as raised:
        current_user(None, _bearer("not.a.real.jwt"), db)

    assert raised.value.status_code == 401


def test_an_authkit_token_is_401_where_no_verifier_was_configured(db, coder):
    # A deployment without WORKOS_CLIENT_ID gets `authkit=None`, and the
    # dependency must stay exactly what it was before this plan rather than
    # crash on the None.
    unconfigured = make_current_user_dep(coder)
    _make_user(db, email="orphan@example.com", workos_user_id="user_authkit_2")

    with pytest.raises(HTTPException) as raised:
        unconfigured(None, _bearer(_authkit_token(sub="user_authkit_2")), db)

    assert raised.value.status_code == 401


def test_the_app_factory_passes_a_verifier_into_the_dependency():
    """The AuthKit branch is dead in production unless `create_app` wires it.

    Every test above builds its own dependency, so all of them stay green if
    `create_app` stops passing the verifier -- while every AuthKit session in
    production 401s as "invalid token". Read the closure rather than send a
    token, because the verifier a real app builds resolves keys over the
    network and no test may.
    """
    import inspect

    from agentpit.api import deps
    from agentpit.api.app import create_app

    def _wired(app):
        dep = app.dependency_overrides[deps.get_current_user]
        return inspect.getclosurevars(dep).nonlocals["authkit"]

    assert isinstance(
        _wired(create_app(Settings(workos_client_id="client_wiring"))),
        AuthKitVerifier,
    )
    # And a deployment with no client id gets None through the same wire --
    # the issuer and the JWKS URL are both derived from it, so a verifier
    # built without one could only reject everything.
    assert _wired(create_app(Settings(workos_client_id=""))) is None
