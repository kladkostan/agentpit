"""list_closed_positions reconstructs won positions from REDEEM payouts (the
Active list drops them once the tokens are redeemed). Payout is deduped per
market; entry/PnL come from the user's fills on the winning token."""

import uuid

from agentpit.auth.passwords import hash_password
from agentpit.config import Settings
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite
from agentpit.services.account_service import AccountService


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


def _insert_trade(conn, *, asset, price, size, taker_api_key):
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, SIDE, PRICE, TRADE_SIZE, STATUS, "
        "TAKER_API_KEY) VALUES (%s, %s, 'BUY', %s, %s, 'CONFIRMED', %s)",
        (uuid.uuid4().hex, asset, price, size, taker_api_key),
    )


def test_list_closed_positions_redeem_driven_dedup_and_pnl():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _uid, acct, api_key = TableWrite.create_user(
            conn,
            email="closed@x.com",
            password_hash=hash_password("pw12pw12pw12"),
            handle=None,
        )
        req = CreateMarketRequest(
            question="Win?",
            description="d",
            erc1155_tokens=[("yt", "Yes"), ("nt", "No")],
            slug="win-q",
            condition_id=ConditionId(_hex32("c1")),
            state=MarketState.ACTIVE,
        )
        m = TableWrite.create_market(conn, req, is_polygon_market=False)
        TableWrite.resolve_market(conn, market_id=m.market_id, winning_outcome_index=0)
        # Bought 100 YES @ 0.40 (the winning side).
        _insert_trade(conn, asset="yt", price=400_000, size=100_000_000,
                      taker_api_key=api_key)
        # Two identical REDEEM logs -> deduped to ONE $100 payout (not $200).
        for _ in range(2):
            TableWrite.log_transaction(
                conn, api_key, "REDEEM", m.market_id,
                {"collateral_amount": 100_000_000},
            )

    out = AccountService(db, onchain=None).list_closed_positions(  # type: ignore[arg-type]
        acct.address
    )
    assert len(out) == 1
    p = out[0]
    assert p.outcome == "Yes"
    assert abs(p.currentValue - 100.0) < 1e-6  # deduped payout, not 200
    assert abs(p.size - 100.0) < 1e-6
    assert abs(p.avgPrice - 0.40) < 1e-6
    assert abs(p.cashPnl - 60.0) < 1e-6  # 100 payout - 40 cost


def test_list_closed_positions_includes_losses():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _uid, acct, api_key = TableWrite.create_user(
            conn,
            email="loss@x.com",
            password_hash=hash_password("pw12pw12pw12"),
            handle=None,
        )
        req = CreateMarketRequest(
            question="Lose?",
            description="d",
            erc1155_tokens=[("yt2", "Yes"), ("nt2", "No")],
            slug="lose-q",
            condition_id=ConditionId(_hex32("c2")),
            state=MarketState.ACTIVE,
        )
        m = TableWrite.create_market(conn, req, is_polygon_market=False)
        # YES (idx 0) won; the user bought NO — the losing side.
        TableWrite.resolve_market(conn, market_id=m.market_id, winning_outcome_index=0)
        _insert_trade(conn, asset="nt2", price=500_000, size=50_000_000,
                      taker_api_key=api_key)  # 50 NO @ 0.50
        TableWrite.log_transaction(
            conn, api_key, "REDEEM", m.market_id, {"collateral_amount": 0}
        )

    out = AccountService(db, onchain=None).list_closed_positions(  # type: ignore[arg-type]
        acct.address
    )
    assert len(out) == 1
    p = out[0]
    assert p.outcome == "No"  # the losing outcome the user held
    assert abs(p.currentValue - 0.0) < 1e-6  # lost -> $0
    assert abs(p.size - 50.0) < 1e-6
    assert abs(p.avgPrice - 0.50) < 1e-6
    assert abs(p.cashPnl + 25.0) < 1e-6  # loss = -cost (0.50 * 50)
