"""JWT-gated /usdc_balance endpoint.

The live balance is asserted in
tests/onchain/test_trade_flow.py::test_register_funds_user_and_grants_approvals.
This file only covers the auth gate.
"""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_usdc_balance_requires_auth():
    with TestClient(app) as client:
        assert client.get("/usdc_balance").status_code == 401
