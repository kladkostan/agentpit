"""JWT-gated /balance-allowance endpoint.

The live balance is asserted in
tests/onchain/test_balance_allowance.py.
This file only covers the auth gate.
"""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_balance_allowance_requires_auth():
    with TestClient(app) as client:
        assert client.get("/balance-allowance").status_code == 401
