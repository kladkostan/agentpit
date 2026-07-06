"""AccountService._avg_fill_price must report the TAKER's real per-share cost.
A MINT match (taker BUY vs maker BUY) records the maker's complement price
(1-p) against the taker's asset_id, so averaging raw trade prices skews the
cost basis toward $0.50. The fix flips MINT (maker-BUY) trades to ONE - price."""
import json
import uuid

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.services.account_service import AccountService


def _trade(conn, *, token, price, size, maker_side, side="BUY", taker="bot"):
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, PRICE, TRADE_SIZE, SIDE, STATUS, "
        "TAKER_API_KEY, MAKER_ORDERS) VALUES (%s,%s,%s,%s,%s,'matched',%s,%s)",
        (uuid.uuid4().hex, token, price, size, side, taker,
         json.dumps([{"side": maker_side, "price": price}])),
    )


def test_avg_fill_price_flips_mint_complement():
    db = DbSession(Settings().database_url)
    tok = "costbasis-tok"
    with db.write() as conn:
        # Bot bought YES ~2¢: a normal fill (maker SELL @ 0.02) and a MINT fill
        # (maker BUY, recorded at the 0.98 complement). True cost ≈ 0.02 both.
        _trade(conn, token=tok, price=20_000, size=100, maker_side="SELL")   # 0.02
        _trade(conn, token=tok, price=980_000, size=100, maker_side="BUY")   # records 0.98, paid 0.02
    with db.read() as conn:
        avg = AccountService._avg_fill_price(conn, "bot", tok)
    assert abs(avg - 0.02) < 1e-6, f"expected ~0.02, got {avg} (averaged the 0.98 complement?)"


def test_avg_fill_price_excludes_exit_sells():
    # Real bug: bot BOUGHT NO @ 0.84, then the exit engine partially SOLD it
    # (at 0.21/0.22 and the MINT complements 0.78/0.79). Those sells must not
    # drag the cost basis down — entry stays 0.84, not ~0.61.
    db = DbSession(Settings().database_url)
    tok = "costbasis-exit"
    with db.write() as conn:
        _trade(conn, token=tok, price=840_000, size=100, maker_side="SELL", side="BUY")
        _trade(conn, token=tok, price=210_000, size=30, maker_side="SELL", side="SELL")
        _trade(conn, token=tok, price=780_000, size=30, maker_side="BUY", side="SELL")
    with db.read() as conn:
        avg = AccountService._avg_fill_price(conn, "bot", tok)
    assert abs(avg - 0.84) < 1e-6, f"expected 0.84 (BUY only), got {avg}"


def test_avg_fill_price_normal_fills_unchanged():
    db = DbSession(Settings().database_url)
    tok = "costbasis-normal"
    with db.write() as conn:
        _trade(conn, token=tok, price=600_000, size=100, maker_side="SELL")  # 0.60
        _trade(conn, token=tok, price=620_000, size=100, maker_side="SELL")  # 0.62
    with db.read() as conn:
        avg = AccountService._avg_fill_price(conn, "bot", tok)
    assert abs(avg - 0.61) < 1e-6   # plain size-weighted average, no flip
