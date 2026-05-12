"""Live anvil integration: register → market → split → match → settle on-chain.

Exercises the full happy path against a running anvil + deployed stack.
"""
import secrets
import uuid

from fastapi.testclient import TestClient


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


def test_register_funds_user_and_grants_approvals():
    # Imports inside the test so the conftest env tweaks land first.
    from agentpit.api.app import create_app
    from agentpit.config import Settings
    from agentpit.onchain.contracts import Contracts
    from agentpit.onchain.deployment import Deployment
    from agentpit.onchain.web3_client import Web3Client

    app = create_app()
    client = TestClient(app)

    body = client.post(
        "/register",
        json={"email": _email(), "password": "hunter22hunter22"},
    ).json()
    eth = body["user"]["eth_address"]
    assert body["user"]["onboarded_at"] is not None

    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    w3 = Web3Client(settings, deployment)
    contracts = Contracts(w3.web3, deployment)
    assert contracts.usd.functions.balanceOf(eth).call() == deployment.signup_grant_raw
    assert contracts.usd.functions.allowance(eth, deployment.exchange).call() > 0
    assert contracts.usd.functions.allowance(eth, deployment.ctf).call() > 0
    assert contracts.ctf.functions.isApprovedForAll(eth, deployment.exchange).call()


def test_match_settles_on_chain():
    from agentpit.api.app import create_app
    from agentpit.config import Settings
    from agentpit.db.session import DbSession
    from agentpit.db.table_read import TableRead
    from agentpit.onchain.admin import OnchainAdmin
    from agentpit.onchain.contracts import Contracts
    from agentpit.onchain.deployment import Deployment
    from agentpit.onchain.web3_client import Web3Client

    app = create_app()
    client = TestClient(app)

    a_email = _email()
    b_email = _email()
    ra = client.post("/register", json={"email": a_email, "password": "hunter22hunter22"}).json()
    rb = client.post("/register", json={"email": b_email, "password": "hunter22hunter22"}).json()
    ta, tb = ra["access_token"], rb["access_token"]
    ea, eb = ra["user"]["eth_address"], rb["user"]["eth_address"]

    market = client.post(
        "/markets",
        json={
            "question": f"Live test {secrets.token_hex(4)}?",
            "description": "YES if test passes",
            "outcome_labels": ["YES", "NO"],
        },
    ).json()
    yes_id = int(market["erc1155_tokens"][0][0])

    # Give B some YES tokens via splitPosition so B can SELL.
    settings = Settings()
    d = Deployment.load(settings.deployment_path)
    w = Web3Client(settings, d)
    c = Contracts(w.web3, d)
    admin = OnchainAdmin(w, c)
    db = DbSession(settings.db_path)
    with db.read() as conn:
        user_b = TableRead.get_user_by_email(conn, b_email)
    cond = bytes.fromhex(market["condition_id"]["value"][2:])
    admin.user_split_position(user_b.eth_key, cond, 200_000_000)

    a_pre_usd = admin.usd_balance(ea)
    b_pre_yes = admin.ctf_balance(eb, yes_id)

    pa = client.post(
        "/orders",
        headers=_hdr(ta),
        json={
            "market_id": market["market_id"], "outcome": "YES",
            "side": "BUY", "price": "0.6", "size": 100_000_000,
        },
    ).json()
    assert pa["success"] and pa["status"] == "live"

    pb = client.post(
        "/orders",
        headers=_hdr(tb),
        json={
            "market_id": market["market_id"], "outcome": "YES",
            "side": "SELL", "price": "0.6", "size": 100_000_000,
        },
    ).json()
    assert pb["success"], pb
    assert pb["status"] == "matched"
    assert pb["filledSize"] == "100000000"
    assert pb["txHash"]

    # Verify on-chain settlement: A paid 60M apUSD, received 100M YES tokens.
    assert admin.usd_balance(ea) == a_pre_usd - 60_000_000
    assert admin.ctf_balance(ea, yes_id) == 100_000_000
    assert admin.ctf_balance(eb, yes_id) == b_pre_yes - 100_000_000
