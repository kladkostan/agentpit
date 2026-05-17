"""Auth + onboarding flow tests.

Anvil + the deployed exchange must be running — register hits the faucet
and grants approvals as part of every signup.
"""
from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_jwt_and_user():
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={"email": "alice@example.com", "password": "hunter22hunter22", "handle": "alice"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["handle"] == "alice"
        assert body["user"]["eth_address"].startswith("0x")
        # On-chain onboarding ran during register — faucet + approvals confirmed.
        assert body["user"]["onboarded_at"] is not None


def test_register_rejects_duplicate_email():
    with TestClient(app) as client:
        for _ in range(2):
            resp = client.post(
                "/register",
                json={"email": "dup@example.com", "password": "hunter22hunter22"},
            )
        assert resp.status_code == 409


def test_register_rejects_weak_password():
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={"email": "bob@example.com", "password": "short"},
        )
        assert resp.status_code == 422


def test_login_with_valid_credentials_returns_jwt():
    with TestClient(app) as client:
        client.post(
            "/register",
            json={"email": "carol@example.com", "password": "hunter22hunter22"},
        )
        resp = client.post(
            "/login",
            json={"email": "carol@example.com", "password": "hunter22hunter22"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]


def test_login_with_wrong_password_is_unauthorized():
    with TestClient(app) as client:
        client.post(
            "/register",
            json={"email": "dan@example.com", "password": "hunter22hunter22"},
        )
        resp = client.post(
            "/login",
            json={"email": "dan@example.com", "password": "nope-nope-nope"},
        )
        assert resp.status_code == 401


def test_me_requires_bearer_token():
    with TestClient(app) as client:
        assert client.get("/me").status_code == 401


def test_me_returns_current_user():
    with TestClient(app) as client:
        token = client.post(
            "/register",
            json={"email": "eve@example.com", "password": "hunter22hunter22"},
        ).json()["access_token"]
        resp = client.get("/me", headers=_hdr(token))
        assert resp.status_code == 200
        assert resp.json()["email"] == "eve@example.com"


def test_me_rejects_invalid_token():
    with TestClient(app) as client:
        resp = client.get("/me", headers=_hdr("not.a.real.jwt"))
        assert resp.status_code == 401
