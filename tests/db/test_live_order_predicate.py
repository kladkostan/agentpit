"""What the book counts as a live order.

An order carries its own death: `EXPIRATION` is a unix second, and zero means
never. The fragment below is the single definition every read shares, and it
subtracts a minute — Polymarket's grace, which their clients compensate for
by adding sixty seconds when they ask for a lifetime.
"""
import time

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead


def _order(conn, *, token: str, expiration: int | None, order_id: str) -> None:
    conn.execute(
        "INSERT INTO orders (ORDER_ID, TOKEN_ID, SIDE, PRICE, STATUS, "
        "REMAINING_AMOUNT, EXPIRATION, CREATED_AT, API_KEY) "
        "VALUES (%s, %s, 'BUY', 500000, 'live', 1000000, %s, %s, 'k')",
        (order_id, token, expiration, int(time.time())),
    )


def test_a_zero_expiration_never_dies():
    db = DbSession(Settings().database_url)
    now = int(time.time())
    with db.write() as conn:
        _order(conn, token="t-never", expiration=0, order_id="o-never")
        rows = conn.execute(
            f"SELECT ORDER_ID FROM orders WHERE TOKEN_ID = 't-never' "
            f"AND {TableRead.LIVE_ORDER}",
            (now,),
        ).fetchall()
    assert [r["ORDER_ID"] for r in rows] == ["o-never"]


def test_an_order_dies_a_minute_before_its_stated_expiration():
    # The rule nobody would guess from the field name: an order stamped to
    # expire in 90 seconds is already gone at 30.
    db = DbSession(Settings().database_url)
    now = int(time.time())
    with db.write() as conn:
        _order(conn, token="t-grace", expiration=now + 90, order_id="o-grace")
        alive = conn.execute(
            f"SELECT ORDER_ID FROM orders WHERE TOKEN_ID = 't-grace' "
            f"AND {TableRead.LIVE_ORDER}",
            (now,),
        ).fetchall()
        dead = conn.execute(
            f"SELECT ORDER_ID FROM orders WHERE TOKEN_ID = 't-grace' "
            f"AND {TableRead.LIVE_ORDER}",
            (now + 31,),
        ).fetchall()
    assert len(alive) == 1
    assert dead == []


def test_the_grace_is_a_minute_and_is_stated_once():
    assert TableRead.EXPIRY_GRACE_SECONDS == 60


def test_a_null_expiration_never_dies():
    # EXPIRATION is a nullable BIGINT with no DEFAULT, so a direct write that
    # omits it (a test fixture, a future migration) leaves it NULL rather
    # than 0. NULL must read the same as "never expires" — otherwise the row
    # is not just invisible to book/price reads, it is UNCANCELLABLE, since
    # cancel_orders/cancel_all route through this same predicate.
    db = DbSession(Settings().database_url)
    now = int(time.time())
    with db.write() as conn:
        _order(conn, token="t-null", expiration=None, order_id="o-null")
        rows = conn.execute(
            f"SELECT ORDER_ID FROM orders WHERE TOKEN_ID = 't-null' "
            f"AND {TableRead.LIVE_ORDER}",
            (now,),
        ).fetchall()
    assert [r["ORDER_ID"] for r in rows] == ["o-null"]
