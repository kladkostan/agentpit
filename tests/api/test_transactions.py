"""JWT-gated /transactions endpoint.

Replaces the deleted tests/api/test_history.py. The legacy SPLIT/MERGE/REDEEM
audit rows were written by the simulator-era TableWrite paths; in the on-chain
flow we don't yet emit per-action audit rows (a follow-up task), so this only
verifies the empty-list path and the auth gate.
"""
from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_transactions_requires_auth():
    with TestClient(app) as client:
        assert client.get("/transactions").status_code == 401


def test_transactions_initially_empty():
    with TestClient(app) as client:
        token = client.post(
            "/register",
            json={"email": "h@example.com", "password": "hunter22hunter22"},
        ).json()["access_token"]
        resp = client.get("/transactions", headers=_hdr(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["eth_address"].startswith("0x")
        assert body["transactions"] == []
