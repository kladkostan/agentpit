import uuid
from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.liquidity import price_oracle
from agentpit.liquidity.engine import LiquidityEngine
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead


def test_one_tick_builds_two_sided_book_no_trades(monkeypatch):
    app = create_app()
    client = TestClient(app)
    m = client.post("/markets", json={
        "question": f"LE {uuid.uuid4().hex[:6]}?", "description": "x",
        "outcome_labels": ["YES", "NO"]}).json()
    cond = m["condition_id"]["value"]

    s = Settings(liquidity_house_account_count=3, liquidity_funding_drips=1,
                 liquidity_makers_per_market=2, liquidity_split_per_market_usdc=50)
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d))
    db = DbSession(s.database_url)

    with db.write() as conn:
        conn.execute(
            "UPDATE markets SET MARKET_STATE='ACTIVE', POLYMARKET_CONDITION_ID=%s, "
            "POLYMARKET_YES_TOKEN_ID=%s WHERE CONDITION_ID=%s",
            ("0xpm", "PMYES", cond),
        )

    house = HouseAccountProvisioner(db, admin, s).ensure_provisioned()
    # Stub the real Polymarket mid at 0.50. Patch the module function the engine
    # calls (NOT price_oracle.get — the getter default is bound at def time).
    monkeypatch.setattr(
        price_oracle, "fetch_mids_for_markets",
        lambda markets, **kw: {mk.market_id: 500_000 for mk in markets},
    )

    LiquidityEngine(db, admin, s, house).tick()

    with db.read() as conn:
        market = TableRead.list_active_synced_markets(conn)[0]
    yes_token = market.erc1155_tokens[0][0]

    book = client.get(f"/book?token_id={yes_token}").json()
    assert book["bids"] and book["asks"]
    best_bid = max(float(b["price"]) for b in book["bids"])
    best_ask = min(float(a["price"]) for a in book["asks"])
    assert best_bid < 0.5 < best_ask

    with db.read() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS C FROM trades WHERE MARKET = %s", (cond,)
        ).fetchone()["C"]
    assert n == 0
