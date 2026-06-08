"""trades ledger owner-attribution (§7): MARKET=condition_id, api_key columns
populated, MAKER_ORDERS carries USER_ID owner + maker_address."""

import json
import secrets
import sqlite3
import uuid

from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _email():
    return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


def test_trade_row_is_owner_attributed():
    app = create_app()
    client = TestClient(app)
    ra = client.post("/register", json={"email": _email(), "password": "hunter22hunter22"}).json()
    b_email = _email()
    rb = client.post("/register", json={"email": b_email, "password": "hunter22hunter22"}).json()
    ta, tb = ra["access_token"], rb["access_token"]
    a_uid = ra["user"]["user_id"]

    market = client.post("/markets", json={
        "question": f"Enrich {secrets.token_hex(4)}?", "description": "x",
        "outcome_labels": ["YES", "NO"]}).json()
    yes = market["erc1155_tokens"][0][0]
    cond = market["condition_id"]["value"]

    settings = Settings()
    d = Deployment.load(settings.deployment_path)
    w = Web3Client(settings, d)
    c = Contracts(w.web3, d)
    admin = OnchainAdmin(w, c)
    db = DbSession(settings.database_url)
    with db.read() as conn:
        user_b = TableRead.get_user_by_email(conn, b_email)
    admin.user_split_position(user_b.eth_key, bytes.fromhex(cond[2:]), 200_000_000)

    # A rests a BUY YES @0.6 (maker); B SELLs YES @0.6 (taker) → settled match.
    client.post("/order", headers=_hdr(ta), json={"token_id": yes, "side": "BUY", "price": "0.6", "size": 100})
    client.post("/order", headers=_hdr(tb), json={"token_id": yes, "side": "SELL", "price": "0.6", "size": 100})

    with db.read() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM trades WHERE ASSET_ID = ? ORDER BY MATCH_TIME DESC LIMIT 1",
            (yes,),
        ).fetchone()
    assert row["MARKET"] == cond                  # condition_id, not token_id
    assert row["ASSET_ID"] == yes
    makers = json.loads(row["MAKER_ORDERS"])
    assert makers[0]["owner"] == a_uid            # USER_ID, not eth/api_key
    assert makers[0]["maker_address"].startswith("0x")
    assert makers[0]["asset_id"] == yes
    assert row["TAKER_API_KEY"] and row["MAKER_API_KEY"]
    assert row["TAKER_API_KEY"] != row["MAKER_API_KEY"]
