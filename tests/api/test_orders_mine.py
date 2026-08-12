"""GET /data/orders returns the caller's open orders (bare OpenOrder[])."""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_data_orders_empty_for_new_user(sign_in):
    with TestClient(app) as client:
        body = sign_in(client, "mine1@example.com")
        resp = client.get("/data/orders", headers=_hdr(body["access_token"]))
        assert resp.status_code == 200, resp.text
        assert resp.json() == []


def test_data_orders_requires_auth():
    with TestClient(app) as client:
        assert client.get("/data/orders").status_code == 401
