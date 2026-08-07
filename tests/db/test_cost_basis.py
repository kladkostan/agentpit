"""AccountService._avg_fill_price must report the TAKER's real per-share cost.
A MINT match records the maker's complement price (1-p) against the taker's
asset_id, so averaging raw trade prices skews the cost basis toward $0.50.
The fix reads MATCH_KIND (not a maker-side heuristic) and flips the taker
leg of a MINT row to ONE - price."""
import json
import uuid

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.services.account_service import AccountService


def _trade(conn, *, token, price, size, maker_side, side="BUY", taker="bot",
           match_kind=None):
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, PRICE, TRADE_SIZE, SIDE, STATUS, "
        "TAKER_API_KEY, MAKER_ORDERS, MATCH_KIND) "
        "VALUES (%s,%s,%s,%s,%s,'matched',%s,%s,%s)",
        (uuid.uuid4().hex, token, price, size, side, taker,
         json.dumps([{"side": maker_side, "price": price}]), match_kind),
    )


def test_avg_fill_price_flips_mint_complement():
    db = DbSession(Settings().database_url)
    tok = "costbasis-tok"
    with db.write() as conn:
        # Bot bought YES ~2¢: a normal fill (maker SELL @ 0.02) and a MINT fill
        # (maker BUY, recorded at the 0.98 complement). True cost ≈ 0.02 both.
        # MATCH_KIND is what `_token_flow` now keys off (not the maker-side
        # heuristic), so the mint leg must declare it explicitly.
        _trade(conn, token=tok, price=20_000, size=100, maker_side="SELL")   # 0.02
        _trade(conn, token=tok, price=980_000, size=100, maker_side="BUY",
               match_kind="MINT")   # records 0.98, paid 0.02
    with db.read() as conn:
        avg = AccountService._avg_fill_price(conn, "bot", tok)
    assert abs(avg - 0.02) < 1e-6, f"expected ~0.02, got {avg} (averaged the 0.98 complement?)"


def test_avg_fill_price_excludes_exit_sells():
    # Real bug: bot BOUGHT NO @ 0.84, then the exit engine partially SOLD it
    # (at 0.21 and 0.78 — neither row carries MATCH_KIND, so both take the
    # NORMAL path and are stored at the price actually sold, no flip). Those
    # sells must not drag the cost basis down — entry stays 0.84, not ~0.61.
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


def test_avg_fill_price_excludes_the_users_own_maker_side_sells():
    """A resting ask that gets hit is a SELL by the account that placed it.

    The stored SIDE is the TAKER's, and the row is reachable from either
    counterparty, so filtering `SIDE = 'BUY'` alone folds the account's own
    maker-side sells into the price it supposedly PAID. Every other case here
    leaves MAKER_API_KEY null, which is exactly why this went unnoticed: it is
    the only shape that exercises the maker branch.
    """
    db = DbSession(Settings().database_url)
    tok = "costbasis-maker-sell"
    with db.write() as conn:
        # Bought 100 @ 0.30 as the taker.
        _trade(conn, token=tok, price=300_000, size=100, maker_side="SELL")
        # Then its resting ask @ 0.60 was hit for 40: the taker bought, WE sold.
        conn.execute(
            "INSERT INTO trades (TRADE_ID, ASSET_ID, PRICE, TRADE_SIZE, SIDE, "
            "STATUS, TAKER_API_KEY, MAKER_API_KEY, MAKER_ORDERS) "
            "VALUES (%s,%s,%s,%s,'BUY','matched',%s,%s,%s)",
            (uuid.uuid4().hex, tok, 600_000, 40, "someone-else", "bot",
             json.dumps([{"side": "SELL", "price": 600_000}])),
        )
    with db.read() as conn:
        avg = AccountService._avg_fill_price(conn, "bot", tok)
    assert abs(avg - 0.30) < 1e-6, (
        f"expected 0.30, got {avg} — the account's own sell was counted as a buy"
    )
