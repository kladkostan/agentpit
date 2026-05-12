"""JWT-gated /usdc_balance endpoint.

Replaces the deleted tests/api/test_usdc.py. The /mint_usdc and /transfer_usdc
routes are gone — minting now happens automatically at signup via the on-chain
faucet — so this file only covers the read path. With on-chain disabled in
unit tests, balance reads return 0; the live balance is asserted in
tests/onchain/test_trade_flow.py::test_register_funds_user_and_grants_approvals.
"""
from fastapi.testclient import TestClient

from agentpit.api.main import app


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_usdc_balance_requires_auth():
    with TestClient(app) as client:
        assert client.get("/usdc_balance").status_code == 401


def test_usdc_balance_returns_zero_when_onchain_disabled():
    with TestClient(app) as client:
        body = client.post(
            "/register",
            json={"email": "u@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.get("/usdc_balance", headers=_hdr(body["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["eth_address"] == body["user"]["eth_address"]
        assert resp.json()["balance"] == 0
