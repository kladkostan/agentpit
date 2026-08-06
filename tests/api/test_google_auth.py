"""Google sign-in: linking rules, the disabled state, and the promise that a
Google signup and a password signup leave the same account behind.

Anvil + the deployed exchange must be running — a Google signup mints a wallet
and runs the same on-chain onboarding a password signup does.
"""

import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_google_verifier
from agentpit.api.main import app
from agentpit.auth.google import GoogleIdentity
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import InvalidCredentialsError
from tests.db_helpers import fresh_test_conn


class _StubVerifier:
    """Maps a fake credential string to an identity; anything else is bad."""

    def __init__(self, identities: dict[str, GoogleIdentity]):
        self._identities = identities

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            return self._identities[credential]
        except KeyError:
            raise InvalidCredentialsError("invalid Google credential") from None


@pytest.fixture
def google():
    """Override the app's verifier for one test and put it back afterwards.

    The app is a module-level singleton shared by the whole suite, so a leaked
    override would silently change every later test's idea of who is signing in.
    """

    def _install(identities: dict[str, GoogleIdentity]) -> None:
        app.dependency_overrides[get_google_verifier] = lambda: _StubVerifier(
            identities
        )

    previous = app.dependency_overrides.get(get_google_verifier)
    yield _install
    if previous is None:
        app.dependency_overrides.pop(get_google_verifier, None)
    else:
        app.dependency_overrides[get_google_verifier] = previous


ALICE = GoogleIdentity(sub="google-sub-alice", email="alice@example.com")


def test_first_google_sign_in_creates_an_account(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "cred-alice"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["created"] is True
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["eth_address"].startswith("0x")
        assert body["user"]["onboarded_at"] is not None
        assert body["user"]["handle"], "a Google signup must not be nameless"


def test_second_google_sign_in_returns_the_same_account(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        first = client.post("/auth/google", json={"credential": "cred-alice"}).json()
        second = client.post("/auth/google", json={"credential": "cred-alice"}).json()
        assert second["created"] is False
        assert second["user"]["user_id"] == first["user"]["user_id"]
        assert second["user"]["eth_address"] == first["user"]["eth_address"]


def test_google_sign_in_links_to_a_matching_password_account(google):
    """Same person, new door. One address is one account — a second row would be
    a second wallet, a second balance and a second row on the board."""
    google({"cred-bob": GoogleIdentity(sub="google-sub-bob", email="bob@example.com")})
    with TestClient(app) as client:
        registered = client.post(
            "/register",
            json={"email": "bob@example.com", "password": "hunter22hunter22"},
        ).json()
        linked = client.post("/auth/google", json={"credential": "cred-bob"}).json()

        assert linked["created"] is False
        assert linked["user"]["user_id"] == registered["user"]["user_id"]
        assert linked["user"]["eth_address"] == registered["user"]["eth_address"]

    conn = fresh_test_conn()
    found = TableRead.get_user_by_google_sub(conn, "google-sub-bob")
    assert found is not None and found.email == "bob@example.com"
    conn.close()


def test_linking_ignores_email_case(google):
    google({"cred-carol": GoogleIdentity(sub="sub-carol", email="carol@example.com")})
    with TestClient(app) as client:
        registered = client.post(
            "/register",
            json={"email": "Carol@Example.com", "password": "hunter22hunter22"},
        ).json()
        linked = client.post("/auth/google", json={"credential": "cred-carol"}).json()
        assert linked["user"]["user_id"] == registered["user"]["user_id"]


def test_a_rejected_credential_is_unauthorized(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "forged"})
        assert resp.status_code == 401


def test_endpoint_is_unavailable_when_no_client_id_is_configured():
    """Absent rather than broken: with no GOOGLE_CLIENT_ID the app builds no
    verifier, and the request is refused before any token is looked at."""
    previous = app.dependency_overrides.get(get_google_verifier)
    app.dependency_overrides[get_google_verifier] = lambda: None
    try:
        with TestClient(app) as client:
            resp = client.post("/auth/google", json={"credential": "anything"})
            assert resp.status_code == 503
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_google_verifier, None)
        else:
            app.dependency_overrides[get_google_verifier] = previous


def test_password_login_into_a_google_account_says_so(google):
    """Not "invalid email or password" — that sends somebody who has forgotten
    which door they used around in a circle."""
    google({"cred-dave": GoogleIdentity(sub="sub-dave", email="dave@example.com")})
    with TestClient(app) as client:
        client.post("/auth/google", json={"credential": "cred-dave"})
        resp = client.post(
            "/login", json={"email": "dave@example.com", "password": "hunter22hunter22"}
        )
        assert resp.status_code == 401
        assert "google" in resp.json()["detail"].lower()


def test_changing_the_password_of_a_google_account_says_so(google):
    """There is no password to change, and 404 "User not found" would be a lie
    told to somebody who is signed in."""
    google({"cred-erin": GoogleIdentity(sub="sub-erin", email="erin@example.com")})
    with TestClient(app) as client:
        token = client.post(
            "/auth/google", json={"credential": "cred-erin"}
        ).json()["access_token"]
        resp = client.patch(
            "/me/password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "hunter22hunter22",
                "new_password": "newhunter22hunter22",
            },
        )
        assert resp.status_code == 400
        assert "google" in resp.json()["detail"].lower()


def test_login_with_an_unknown_email_is_still_generic():
    """The Google message is for accounts that exist. A stranger learns nothing
    beyond what registration's 409 already tells them."""
    with TestClient(app) as client:
        resp = client.post(
            "/login", json={"email": "ghost@example.com", "password": "hunter22hunter22"}
        )
        assert resp.status_code == 401
        assert "google" not in resp.json()["detail"].lower()


def test_google_signup_and_password_signup_leave_the_same_state(google):
    """The test that keeps the two paths from drifting. Both accounts must come
    out with a wallet, a funded chain balance, a handle, a recorded deposit and
    a recorded deployment — the difference between them is the credential and
    nothing else."""
    google({"cred-frank": GoogleIdentity(sub="sub-frank", email="frank@example.com")})
    with TestClient(app) as client:
        by_password = client.post(
            "/register",
            json={"email": "grace@example.com", "password": "hunter22hunter22"},
        ).json()["user"]
        by_google = client.post(
            "/auth/google", json={"credential": "cred-frank"}
        ).json()["user"]

    for account in (by_password, by_google):
        assert account["eth_address"].startswith("0x")
        assert account["api_key"]
        assert account["handle"]
        assert account["onboarded_at"] is not None

    default_raw = -1  # any read that falls through to the default is a failure
    conn = fresh_test_conn()
    try:
        for account in (by_password, by_google):
            user_id = account["user_id"]
            assert TableRead.get_total_deposited(conn, user_id, default_raw) > 0
            assert TableRead.get_deployment_id(conn, user_id) is not None
        assert TableRead.get_password_hash_by_userid(
            conn, by_password["user_id"]
        ) is not None
        assert TableRead.get_password_hash_by_userid(
            conn, by_google["user_id"]
        ) is None
    finally:
        conn.close()
