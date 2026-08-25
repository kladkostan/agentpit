"""GET /balance-allowance (§8.12). Live-chain (reads on-chain balances)."""

import secrets
import uuid

from fastapi.testclient import TestClient

from agentpit.api.app import create_app

from tests.onchain._helpers import ADMIN_HDR, hdr, register


def _hdr(t):
    # One definition of the suite's credential lives in _helpers; six local
    # copies is how this file kept sending a bearer token after the cutover
    # made the API key the thing tests can actually mint.
    return hdr(t)


def _email():
    return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


def test_collateral_balance_is_signup_grant():
    from agentpit.config import Settings
    from agentpit.onchain.deployment import Deployment

    app = create_app()
    client = TestClient(app)
    body = register(client, _email())
    grant = Deployment.load(Settings().deployment_path).signup_grant_raw

    resp = client.get("/balance-allowance", headers=_hdr(body["access_token"])).json()
    assert resp == {"balance": str(grant), "allowances": {}}


def test_conditional_balance_zero_and_requires_token_id():
    app = create_app()
    client = TestClient(app)
    reg = register(client, _email())
    tok = reg["access_token"]
    market = client.post("/markets", json={
        "question": f"Bal {secrets.token_hex(4)}?", "description": "x",
        "outcome_labels": ["YES", "NO"]}, headers=ADMIN_HDR).json()
    yes = market["erc1155_tokens"][0][0]

    resp = client.get(
        f"/balance-allowance?asset_type=CONDITIONAL&token_id={yes}", headers=_hdr(tok)
    ).json()
    assert resp == {"balance": "0", "allowances": {}}

    # CONDITIONAL without token_id → 400.
    assert client.get(
        "/balance-allowance?asset_type=CONDITIONAL", headers=_hdr(tok)
    ).status_code == 400

    # signature_type is accepted and ignored.
    ok = client.get("/balance-allowance?signature_type=0", headers=_hdr(tok))
    assert ok.status_code == 200
