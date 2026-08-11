import httpx
import pytest

from agentpit.auth.workos_client import (
    FakeWorkOsClient,
    WorkOsError,
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
