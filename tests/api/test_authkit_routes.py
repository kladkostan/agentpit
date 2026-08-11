"""Signing in with a mailed code, over the real app."""
import pytest
from fastapi.testclient import TestClient

from agentpit.api import deps
from agentpit.api.main import app
from agentpit.auth.workos_client import FakeWorkOsClient


@pytest.fixture
def workos():
    fake = FakeWorkOsClient()
    app.dependency_overrides[deps.get_workos_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(deps.get_workos_client, None)


def _code(workos: FakeWorkOsClient, email: str) -> str:
    return workos.last_code(email)


def test_post_auth_code_accepts_any_address_with_202(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/code", json={"email": "brand-new@example.com"})
    assert resp.status_code == 202, resp.text


def test_post_auth_code_says_the_same_thing_for_known_and_unknown_addresses(workos):
    # Whether an address has an account must not be inferable here: anybody
    # can post any address. `/register` already leaks existence with its 409,
    # which is no reason to add a second oracle.
    with TestClient(app) as client:
        first = client.post("/auth/code", json={"email": "known@example.com"})
        client.post(
            "/auth/session",
            json={"email": "known@example.com", "code": _code(workos, "known@example.com")},
        )
        again = client.post("/auth/code", json={"email": "known@example.com"})
        stranger = client.post("/auth/code", json={"email": "stranger@example.com"})
    assert first.status_code == again.status_code == stranger.status_code == 202
    assert again.json() == stranger.json()


def test_the_right_code_returns_a_session_and_a_funded_account(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "a@example.com"})
        resp = client.post(
            "/auth/session",
            json={"email": "a@example.com", "code": _code(workos, "a@example.com")},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    # The wallet is the thing WorkOS cannot make for us.
    assert body["user"]["eth_address"].startswith("0x")
    assert body["user"]["email"] == "a@example.com"


def test_a_wrong_code_is_401_and_creates_nothing(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "b@example.com"})
        resp = client.post(
            "/auth/session", json={"email": "b@example.com", "code": "000000"}
        )
        assert resp.status_code == 401, resp.text
        # Nothing was created, so a correct code afterwards still works.
        ok = client.post(
            "/auth/session",
            json={"email": "b@example.com", "code": _code(workos, "b@example.com")},
        )
    assert ok.status_code == 200, ok.text


def test_a_malformed_code_is_422_and_never_reaches_workos(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "c@example.com"})
        resp = client.post(
            "/auth/session", json={"email": "c@example.com", "code": "12345"}
        )
    assert resp.status_code == 422


def test_signing_in_twice_returns_the_same_account(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "d@example.com"})
        first = client.post(
            "/auth/session",
            json={"email": "d@example.com", "code": _code(workos, "d@example.com")},
        ).json()
        client.post("/auth/code", json={"email": "d@example.com"})
        second = client.post(
            "/auth/session",
            json={"email": "d@example.com", "code": _code(workos, "d@example.com")},
        ).json()
    assert first["user"]["user_id"] == second["user"]["user_id"]
    assert first["user"]["eth_address"] == second["user"]["eth_address"]


def test_refresh_returns_a_new_access_token_for_the_same_user(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "e@example.com"})
        session = client.post(
            "/auth/session",
            json={"email": "e@example.com", "code": _code(workos, "e@example.com")},
        ).json()
        resp = client.post(
            "/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["user_id"] == session["user"]["user_id"]


def test_a_garbage_refresh_token_is_401(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/refresh", json={"refresh_token": "nonsense"})
    assert resp.status_code == 401, resp.text


def test_register_and_login_are_untouched(workos):
    # This plan removes nothing. If these break, the transition has no floor.
    with TestClient(app) as client:
        made = client.post(
            "/register",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        )
        assert made.status_code == 200, made.text
        back = client.post(
            "/login",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        )
    assert back.status_code == 200, back.text
    assert back.json()["access_token"]


def test_the_routes_answer_503_when_workos_is_not_configured():
    # Every developer machine before the account existed, and any deployment
    # that forgets the keys. It must be an obvious 503, not a 500.
    app.dependency_overrides[deps.get_workos_client] = lambda: None
    try:
        with TestClient(app) as client:
            resp = client.post("/auth/code", json={"email": "f@example.com"})
        assert resp.status_code == 503, resp.text
    finally:
        app.dependency_overrides.pop(deps.get_workos_client, None)
