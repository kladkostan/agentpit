import uuid

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

_ORDER_COLS = (
    "API_KEY, PRICE, POST_ONLY, ORDER_TYPE, SALT, MAKER, TAKER, SIGNER, TOKEN_ID, "
    "MAKER_AMOUNT, TAKER_AMOUNT, EXPIRATION, NONCE, FEE_RATE_BPS, SIDE, "
    "SIGNATURE_TYPE, SIGNATURE, ORDER_JSON, STATUS, REMAINING_AMOUNT, CREATED_AT, ORDER_ID"
)


def _insert_order(conn, *, api_key, token, side, price, remaining, status="live"):
    conn.execute(
        f"INSERT INTO orders ({_ORDER_COLS}) VALUES "
        "(%s,%s,0,'GTC','0','0x0','0x0','0x0',%s,0,0,0,0,0,%s,'EIP712','sig','{}',%s,%s,0,%s)",
        (api_key, price, token, side, status, remaining, uuid.uuid4().hex),
    )


def _insert_trade(conn, *, asset, price, match_time, status="MATCHED"):
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, PRICE, MATCH_TIME, STATUS) "
        "VALUES (%s,%s,%s,%s,%s)",
        (uuid.uuid4().hex, asset, price, match_time, status),
    )


def test_book_tops_for_tokens_batches_best_bid_ask():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_order(conn, api_key="m", token="A", side="BUY",
                      price=140_000, remaining=5)
        _insert_order(conn, api_key="m", token="A", side="BUY",
                      price=130_000, remaining=5)   # lower bid
        _insert_order(conn, api_key="m", token="A", side="SELL",
                      price=150_000, remaining=5)
        _insert_order(conn, api_key="m", token="A", side="SELL",
                      price=160_000, remaining=5)   # higher ask
        _insert_order(conn, api_key="m", token="A", side="SELL",
                      price=145_000, remaining=5, status="cancelled")  # not live
        _insert_order(conn, api_key="m", token="B", side="BUY",
                      price=900_000, remaining=5)   # bids only
    with db.read() as conn:
        tops = TableRead.book_tops_for_tokens(conn, ["A", "B", "C"])
        assert TableRead.book_tops_for_tokens(conn, []) == {}
    assert tops["A"] == (140_000, 150_000)  # max live BUY, min live SELL
    assert tops["B"] == (900_000, None)     # one-sided book
    assert "C" not in tops                  # no orders -> absent


def test_last_trade_prices_for_tokens_latest_non_failed():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_trade(conn, asset="A", price=300_000, match_time=100)
        _insert_trade(conn, asset="A", price=320_000, match_time=200)   # latest ok
        _insert_trade(conn, asset="A", price=999_000, match_time=300,
                      status="FAILED")                                  # ignored
        _insert_trade(conn, asset="B", price=500_000, match_time=50)
    with db.read() as conn:
        lasts = TableRead.last_trade_prices_for_tokens(conn, ["A", "B", "C"])
        assert TableRead.last_trade_prices_for_tokens(conn, []) == {}
    assert lasts == {"A": 320_000, "B": 500_000}


def test_list_live_order_levels_scopes_by_key_token_and_status():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_order(conn, api_key="mirror", token="T1", side="BUY",
                      price=400_000, remaining=5)
        _insert_order(conn, api_key="mirror", token="T1", side="SELL",
                      price=600_000, remaining=3, status="cancelled")   # not live
        _insert_order(conn, api_key="mirror", token="T9", side="BUY",
                      price=100_000, remaining=1)                       # other token
        _insert_order(conn, api_key="someone", token="T1", side="BUY",
                      price=410_000, remaining=2)                       # other owner
    with db.read() as conn:
        rows = TableRead.list_live_order_levels(conn, "mirror", ["T1", "T2"])
    assert [(r["TOKEN_ID"], r["SIDE"], int(r["PRICE"]), int(r["REMAINING_AMOUNT"]))
            for r in rows] == [("T1", "BUY", 400_000, 5)]


def test_foreign_touch_excludes_own_orders():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_order(conn, api_key="mirror", token="T3", side="BUY",
                      price=990_000, remaining=1)        # own — must be ignored
        _insert_order(conn, api_key="bot", token="T3", side="BUY",
                      price=450_000, remaining=1)
        _insert_order(conn, api_key="bot2", token="T3", side="SELL",
                      price=520_000, remaining=1)
    with db.read() as conn:
        bid, ask = TableRead.foreign_touch(conn, "mirror", "T3")
        none_bid, none_ask = TableRead.foreign_touch(conn, "mirror", "T-EMPTY")
    assert (bid, ask) == (450_000, 520_000)
    assert (none_bid, none_ask) == (None, None)
