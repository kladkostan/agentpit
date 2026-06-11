import json

import agentpit.polymarket.polymarket_sync as sync
from tests.db_helpers import fresh_test_conn


def _insert(conn, *, cid, state, end_date):
    conn.execute(
        """
        INSERT INTO markets
            (CONDITION_ID, POLYMARKET_CONDITION_ID, QUESTION, SLUG, DESCRIPTION,
             ERC1155_TOKENS, START_DATE, END_DATE, MARKET_STATE)
        VALUES (%s, %s, 'Q?', %s, 'd', %s, 100, %s, %s)
        """,
        (cid, cid, cid, json.dumps([["1", "YES"], ["2", "NO"]]), end_date, state),
    )


def test_mirror_only_fetches_ended_unresolved():
    conn = fresh_test_conn()
    _insert(conn, cid="0xaa", state="ACTIVE", end_date=500)   # ended -> candidate
    _insert(conn, cid="0xbb", state="ACTIVE", end_date=9000)  # not ended
    _insert(conn, cid="0xcc", state="RESOLVED", end_date=500)  # resolved

    fetched = []

    def fake_fetcher(polymarket_condition_id):
        fetched.append(polymarket_condition_id)
        return None  # upstream not resolved -> mirror does nothing further

    # admin is never used on the not-resolved path (fetcher returns None).
    resolved = sync.mirror_polymarket_resolutions(
        conn, admin=None, fetcher=fake_fetcher, now=1000  # type: ignore[arg-type]
    )

    assert resolved == 0
    assert fetched == ["0xaa"]  # only the ended, unresolved market was polled
