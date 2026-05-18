"""GET /orders/mine returns the caller's live orders for reconciliation."""
from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_orders_mine_returns_empty_for_new_user():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "mine1@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.get("/orders/mine", headers=_hdr(body["access_token"]))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"orders": []}


def test_orders_mine_requires_auth():
    with TestClient(app) as client:
        resp = client.get("/orders/mine")
        assert resp.status_code == 401
