"""Taking the key to a wallet that is yours.

agentpit generates the wallet and holds its key. Export is what lets the
account holder put it in MetaMask and fund it. The dangerous path is the
Google one: a valid token proves somebody signed in, not that THIS account's
owner did.

Anvil + the deployed exchange must be running — registering (by password or
Google) runs the same on-chain onboarding every other auth test relies on.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_google_verifier
from agentpit.api.main import app
from agentpit.auth.google import GoogleIdentity, GoogleTokenVerifier
from tests.db_helpers import fresh_test_conn


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
