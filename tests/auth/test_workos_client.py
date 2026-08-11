import json

import httpx
import pytest

from agentpit.auth.workos_client import (
    FakeWorkOsClient,
    WorkOsError,
    WorkOsSession,
    WorkOsUser,
    build_workos_client,
)
from agentpit.config import Settings


def _settings(**over) -> Settings:
    base = {
        "workos_api_key": "sk_test_123",
        "workos_client_id": "client_123",
        "workos_authkit_domain": "https://example.authkit.app",
    }
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


def test_build_returns_none_when_unconfigured():
    # An absent key means the feature is simply not present, exactly as
    # GOOGLE_CLIENT_ID behaves. It must not raise at import or startup.
    assert build_workos_client(_settings(workos_api_key="")) is None


def test_build_returns_a_client_when_configured():
    assert build_workos_client(_settings()) is not None


def test_fake_creates_and_finds_users():
    fake = FakeWorkOsClient()
    created = fake.create_user(email="a@b.com", password_hash="$2b$12$abc")
    assert isinstance(created, WorkOsUser)
    assert created.email == "a@b.com"
    assert fake.find_user_by_email("a@b.com") is not None
    assert fake.find_user_by_email("nobody@b.com") is None


def test_fake_create_is_idempotent_on_email():
    # The migration script runs this against every existing row and may be
    # re-run; a second create for the same address must return the first user
    # rather than a duplicate identity.
    fake = FakeWorkOsClient()
    first = fake.create_user(email="a@b.com", password_hash=None)
    second = fake.create_user(email="a@b.com", password_hash=None)
    assert first.workos_user_id == second.workos_user_id


# --- the REAL client, driven over a stub transport -----------------------
#
# These matter more than the fake's tests. A double can only prove the
# contract; only these prove the code that will actually talk to WorkOS --
# its URLs, its auth header, its request body and its parsing. httpx's
# MockTransport runs the real client end to end without a socket.


def _real(handler):
    return build_workos_client(
        _settings(), transport=httpx.MockTransport(handler)
    )


def test_real_client_creates_a_user_with_the_bcrypt_hash():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(
            201,
            json={"id": "user_01", "email": "a@b.com", "email_verified": True},
        )

    client = _real(handler)
    user = client.create_user(email="a@b.com", password_hash="$2b$12$abc")

    assert user == WorkOsUser(
        workos_user_id="user_01", email="a@b.com", email_verified=True
    )
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/user_management/users")
    assert seen["auth"] == "Bearer sk_test_123"
    body = seen["body"].decode()
    # The hash travels as an imported foreign hash, which is the entire point:
    # get this pair wrong and every migrated account is locked out of its own
    # password with no error anywhere.
    assert '"password_hash": "$2b$12$abc"' in body.replace("\n", "")
    assert '"password_hash_type": "bcrypt"' in body.replace("\n", "")


def test_real_client_omits_the_password_fields_when_there_is_no_hash():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        return httpx.Response(
            201, json={"id": "user_02", "email": "g@b.com", "email_verified": True}
        )

    _real(handler).create_user(email="g@b.com", password_hash=None)

    # A Google-sourced account has no password. Sending `password_hash: null`
    # is not the same request as omitting it, and the API is entitled to
    # reject it.
    assert "password_hash" not in seen["body"]


def test_real_client_finds_an_existing_user_by_email():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "email=a%40b.com" in str(request.url)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "user_03", "email": "a@b.com", "email_verified": True}
                ]
            },
        )

    found = _real(handler).find_user_by_email("a@b.com")
    assert found is not None and found.workos_user_id == "user_03"


def test_real_client_returns_none_for_an_unknown_email():
    found = _real(lambda _r: httpx.Response(200, json={"data": []})).find_user_by_email(
        "nobody@b.com"
    )
    assert found is None


def test_real_client_create_is_idempotent_on_email():
    # Same contract the fake promises, proven against the real code path: the
    # migration script re-runs, and a second call must not mint a second
    # identity for one person.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "user_04", "email": "a@b.com", "email_verified": True}
                    ]
                },
            )
        raise AssertionError("must not POST when the user already exists")

    user = _real(handler).create_user(email="a@b.com", password_hash="$2b$12$x")
    assert user.workos_user_id == "user_04"


def test_an_api_error_becomes_a_workos_error():
    # The migration script catches per account and continues; it can only do
    # that if failures arrive as one predictable type rather than as whatever
    # httpx felt like raising.
    client = _real(lambda _r: httpx.Response(422, json={"message": "bad"}))
    with pytest.raises(WorkOsError):
        client.create_user(email="a@b.com", password_hash=None)


def test_the_api_key_never_appears_in_the_error():
    # A traceback from this client can reach logs. The bearer token must not
    # ride along in it.
    client = _real(lambda _r: httpx.Response(500, text="boom"))
    with pytest.raises(WorkOsError) as exc:
        client.find_user_by_email("a@b.com")
    assert "sk_test_123" not in str(exc.value)


# --- Magic Auth: send a code, trade it for a session, refresh it ----------


def test_send_magic_auth_code_posts_the_address():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={
            "id": "magic_auth_01", "user_id": "user_01",
            "email": "a@b.com", "code": "515627",
        })

    _real(handler).send_magic_auth_code("a@b.com")
    assert seen["url"].endswith("/user_management/magic_auth")
    assert '"email": "a@b.com"' in seen["body"].replace("\n", "")


def test_the_returned_code_is_never_exposed():
    # WorkOS returns the code in the create response, which means anyone
    # holding the API key can sign in as anyone without reading email. That is
    # inherent to the key, but the code must not travel any further than this
    # method: `send_magic_auth_code` returns None on purpose.
    resp = {"id": "m", "user_id": "u", "email": "a@b.com", "code": "515627"}
    assert _real(lambda _r: httpx.Response(201, json=resp)).send_magic_auth_code(
        "a@b.com"
    ) is None


def test_authenticate_with_code_returns_a_session():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "user": {"id": "user_01", "email": "a@b.com", "email_verified": True},
            "access_token": "at", "refresh_token": "rt",
            "authentication_method": "MagicAuth",
        })

    session = _real(handler).authenticate_with_code("a@b.com", "515627")
    assert session == WorkOsSession(
        workos_user_id="user_01", email="a@b.com",
        access_token="at", refresh_token="rt",
    )
    # The grant type is a magic string; a typo in it returns a 400 that reads
    # like a bad code, so pin it.
    assert seen["body"]["grant_type"] == (
        "urn:workos:oauth:grant-type:magic-auth:code"
    )
    assert seen["body"]["client_id"] == "client_123"
    assert seen["body"]["client_secret"] == "sk_test_123"
    assert seen["body"]["code"] == "515627"
    # The magic-auth grant requires the address alongside the code. Dropping it
    # 400s on every sign-in with an error that reads like a bad code, so pin it
    # here too rather than discovering it in production.
    assert seen["body"]["email"] == "a@b.com"


def test_a_wrong_code_raises_workos_error():
    client = _real(lambda _r: httpx.Response(400, json={"code": "invalid_code"}))
    with pytest.raises(WorkOsError):
        client.authenticate_with_code("a@b.com", "000000")


def test_the_api_key_never_appears_in_an_authenticate_error():
    # /user_management/authenticate is the one call that puts the API key in
    # the request BODY, and it is reached by an unauthenticated caller who
    # supplies the code. Measured, WorkOS itself answers `{"code":
    # "invalid_code"}` and echoes nothing -- but a gateway in front of it may,
    # and plan 3 turns this message into a user-visible 401 `detail`.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": "invalid_request", "received": request.read().decode()},
        )

    with pytest.raises(WorkOsError) as exc:
        _real(handler).authenticate_with_code("a@b.com", "000000")
    assert "sk_test_123" not in str(exc.value)


def test_refresh_session_uses_the_refresh_grant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "user": {"id": "user_01", "email": "a@b.com", "email_verified": True},
            "access_token": "at2", "refresh_token": "rt2",
        })

    session = _real(handler).refresh_session("rt")
    assert session.access_token == "at2" and session.refresh_token == "rt2"
    assert seen["body"]["grant_type"] == "refresh_token"
    assert seen["body"]["refresh_token"] == "rt"


def test_fake_round_trips_a_code():
    fake = FakeWorkOsClient()
    fake.send_magic_auth_code("a@b.com")
    session = fake.authenticate_with_code("a@b.com", fake.last_code("a@b.com"))
    assert session.email == "a@b.com"
    assert session.workos_user_id == fake.find_user_by_email("a@b.com").workos_user_id


def test_fake_rejects_a_wrong_code():
    fake = FakeWorkOsClient()
    fake.send_magic_auth_code("a@b.com")
    with pytest.raises(WorkOsError):
        fake.authenticate_with_code("a@b.com", "000000")


def test_fake_rejects_a_code_issued_for_another_address():
    # A code is bound to the address it was mailed to. If the double issued one
    # constant code to everybody it would accept Alice's code presented for
    # Mallory's address, and a service that authenticated against the wrong
    # email would pass its tests.
    fake = FakeWorkOsClient()
    fake.send_magic_auth_code("alice@b.com")
    fake.send_magic_auth_code("mallory@b.com")
    assert fake.last_code("alice@b.com") != fake.last_code("mallory@b.com")
    with pytest.raises(WorkOsError):
        fake.authenticate_with_code("mallory@b.com", fake.last_code("alice@b.com"))


def test_fake_creates_the_user_on_first_code_like_the_real_api_does():
    fake = FakeWorkOsClient()
    assert fake.find_user_by_email("new@b.com") is None
    fake.send_magic_auth_code("new@b.com")
    assert fake.find_user_by_email("new@b.com") is not None
