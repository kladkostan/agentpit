"""purge_cancelled_orders removes only cancelled orders older than the cutoff —
keeping live/matched rows and recent cancellations — so fast re-quoting can't
grow the orders table without bound."""

import uuid

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite


def _insert(conn, *, status: str, created_at: int) -> None:
    conn.execute(
        "INSERT INTO orders (TOKEN_ID, SIDE, PRICE, STATUS, REMAINING_AMOUNT, "
        "CREATED_AT, ORDER_ID) VALUES ('T', 'BUY', 500000, %s, 1, %s, %s)",
        (status, created_at, uuid.uuid4().hex),
    )


def test_purge_cancelled_orders_removes_only_old_cancelled():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert(conn, status="cancelled", created_at=100)  # old cancelled -> purged
        _insert(conn, status="cancelled", created_at=900)  # recent cancelled -> kept
        _insert(conn, status="live", created_at=100)       # live -> kept
        _insert(conn, status="matched", created_at=100)    # matched -> kept
        removed = TableWrite.purge_cancelled_orders(conn, before_ts=500)
    assert removed == 1
    with db.read() as conn:
        rows = conn.execute(
            "SELECT STATUS, CREATED_AT FROM orders"
        ).fetchall()
    kept = sorted((r["STATUS"], int(r["CREATED_AT"])) for r in rows)
    assert kept == [("cancelled", 900), ("live", 100), ("matched", 100)]
