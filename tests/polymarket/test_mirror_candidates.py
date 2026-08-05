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


def test_a_market_upstream_closes_before_its_stated_end_date():
    """Polymarket dates a short-lived sports market to the END OF THE TOURNAMENT,
    not the end of the match. Measured on production: a tennis match played and
    settled on 5 August carried end_date_iso 2026-08-13, so `END_DATE < now`
    never selected it and the mirror never looked -- 208 of 211 book-less ACTIVE
    markets were in exactly this state. The upstream document is fetchable and
    says `closed` with a winner the whole time; only the candidate filter was in
    the way."""
    conn = fresh_test_conn()
    _insert(conn, cid="0xfuture", state="ACTIVE", end_date=9000)

    seen = []

    def fake_fetcher(polymarket_condition_id):
        seen.append(polymarket_condition_id)
        return None

    sync.mirror_polymarket_resolutions(
        conn,
        admin=None,  # type: ignore[arg-type]
        fetcher=fake_fetcher,
        now=1000,
        candidates=sync.list_scan_candidates(conn, after_market_id=0, limit=50),
    )

    assert seen == ["0xfuture"]


def test_the_scan_rotates_so_one_pass_cannot_starve_the_rest():
    """The end-date filter also bounded cost: one upstream fetch per candidate
    per pass. Scanning everything every cycle would be ~2,400 fetches, so the
    scan takes a slice and resumes after the highest id it returned."""
    conn = fresh_test_conn()
    for cid in ("0x01", "0x02", "0x03"):
        _insert(conn, cid=cid, state="ACTIVE", end_date=9000)

    first = sync.list_scan_candidates(conn, after_market_id=0, limit=2)
    assert len(first) == 2

    second = sync.list_scan_candidates(
        conn, after_market_id=first[-1].market_id, limit=2
    )
    assert len(second) == 1
    assert {m.market_id for m in first}.isdisjoint({m.market_id for m in second})

    # past the end it returns nothing, which is the caller's cue to wrap to 0
    assert sync.list_scan_candidates(
        conn, after_market_id=second[-1].market_id, limit=2
    ) == []


def test_the_scan_skips_what_is_already_settled():
    conn = fresh_test_conn()
    _insert(conn, cid="0xdone", state="RESOLVED", end_date=9000)
    _insert(conn, cid="0xgone", state="CANCELLED", end_date=9000)
    _insert(conn, cid="0xopen", state="ACTIVE", end_date=9000)

    got = sync.list_scan_candidates(conn, after_market_id=0, limit=50)
    assert [m.polymarket_condition_id for m in got] == ["0xopen"]
