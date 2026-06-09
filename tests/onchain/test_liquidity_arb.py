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
from agentpit.services.order_service import OrderService


def _setup(monkeypatch, box, *, split_per_market_usdc=200, print_size_shares=10):
    app = create_app()
    client = TestClient(app)
    m = client.post("/markets", json={
        "question": f"ARB {uuid.uuid4().hex[:6]}?",
        "description": "x",
        "outcome_labels": ["YES", "NO"],
    }).json()
    cond = m["condition_id"]["value"]
    s = Settings(
        liquidity_house_account_count=5,
        liquidity_funding_drips=1,
        liquidity_makers_per_market=2,
        liquidity_taker_pool_size=2,
        liquidity_split_per_market_usdc=split_per_market_usdc,
        liquidity_print_size_shares=print_size_shares,
        liquidity_print_threshold_micro=5_000,
    )
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
    monkeypatch.setattr(price_oracle, "fetch_bid_ask_micro", lambda tid, **kw: box["v"])
    return db, admin, s, house, cond, m


def _trade_count(db, cond):
    with db.read() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS C FROM trades WHERE MARKET=%s", (cond,)
        ).fetchone()["C"]


def test_arb_print_seeds_and_follows(monkeypatch):
    box = {"v": (490_000, 510_000)}
    db, admin, s, house, cond, m = _setup(monkeypatch, box)
    engine = LiquidityEngine(db, admin, s, house)

    engine.tick()                       # quote + seed one print
    n1 = _trade_count(db, cond)
    assert n1 >= 1, f"tape not seeded: expected >=1 trade, got {n1}"

    with db.read() as conn:
        mk = TableRead.list_active_synced_markets(conn)[0]
    yes_token = mk.erc1155_tokens[0][0]
    last1 = OrderService(db, admin).get_last_trade_price(yes_token)

    box["v"] = (590_000, 610_000)       # Polymarket moved up ~0.10 (> print threshold)
    engine.tick()                       # requote + BUY print
    n2 = _trade_count(db, cond)
    assert n2 > n1, f"second print did not happen: {n2} <= {n1}"
    last2 = OrderService(db, admin).get_last_trade_price(yes_token)
    assert float(last2["price"]) > float(last1["price"]), (
        f"traded price did not follow Polymarket up: {last1['price']} -> {last2['price']}"
    )


def test_no_print_when_fair_stable(monkeypatch):
    box = {"v": (490_000, 510_000)}
    db, admin, s, house, cond, m = _setup(monkeypatch, box)
    engine = LiquidityEngine(db, admin, s, house)
    engine.tick()                       # seed
    n1 = _trade_count(db, cond)
    engine.tick()                       # same fair -> no new print
    assert _trade_count(db, cond) == n1, (
        f"stable fair produced extra print: {_trade_count(db, cond)} != {n1}"
    )


def test_print_larger_than_depth_no_self_trade(monkeypatch):
    # print_size bigger than a single resting level: the taker's FAK remainder
    # must be cancelled, so an opposite-direction print never self-crosses.
    box = {"v": (490_000, 510_000)}
    db, admin, s, house, cond, m = _setup(monkeypatch, box,
        split_per_market_usdc=5, print_size_shares=20)   # print > book depth
    engine = LiquidityEngine(db, admin, s, house)
    engine.tick()                       # BUY print, partial fill, remainder cancelled
    box["v"] = (390_000, 410_000)       # big down-move -> SELL print
    engine.tick()
    with db.read() as conn:
        failed = conn.execute(
            "SELECT COUNT(*) AS C FROM trades WHERE MARKET=%s AND STATUS='FAILED'", (cond,)
        ).fetchone()["C"]
    assert failed == 0                  # no self-trade revert
    # and the takers left no resting orders
    with db.read() as conn:
        live_taker = conn.execute(
            "SELECT COUNT(*) AS C FROM orders WHERE STATUS='live' AND API_KEY = ANY(%s)",
            ([t.api_key for t in engine._takers],),
        ).fetchone()["C"]
    assert live_taker == 0
