"""DB-level: two different windows of one series bind to the SAME agentpit
event (one homepage card). On-chain prepare is faked, so no anvil needed.
"""

import secrets

import agentpit.polymarket.pinned as pinned
import agentpit.polymarket.polymarket_sync as sync
from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


def _window_event(window_ts: int) -> dict:
    """Two distinct windows of the SAME series (id 10684) — unique market
    id/conditionId/question per window so they don't collide on dedup."""
    nonce = secrets.token_hex(4)
    return {
        "id": f"win-{window_ts}",
        "slug": f"btc-updown-5m-{window_ts}",
        "title": f"Bitcoin Up or Down - {window_ts}",
        "series": [
            {"id": "10684", "slug": "btc-up-or-down-5m", "title": "BTC Up or Down 5m"}
        ],
        "markets": [
            {
                "id": int(secrets.token_hex(4), 16),
                "conditionId": "0x" + secrets.token_hex(32),
                "question": f"Bitcoin Up or Down - {window_ts}-{nonce}",
                "description": "d",
                "slug": f"btc-updown-5m-{window_ts}",
                "active": True,
                "closed": False,
                "startDate": "2026-06-11T16:00:00Z",
                "endDate": "2026-06-11T16:05:00Z",
                "clobTokenIds": '["111","222"]',
                "outcomes": '["Up","Down"]',
            }
        ],
    }


def test_two_windows_of_one_series_share_event(monkeypatch):
    conn = fresh_test_conn()

    # Fake on-chain prepare: deterministic local condition/token ids, no anvil.
    def fake_prepare(admin, question, labels):
        cid = ConditionId("0x" + secrets.token_hex(32))
        toks = [
            (str(int(secrets.token_hex(8), 16)), labels[0]),
            (str(int(secrets.token_hex(8), 16)), labels[1]),
        ]
        return cid, toks

    monkeypatch.setattr(sync, "prepare_market_on_chain", fake_prepare)

    events = iter([_window_event(1781193600), _window_event(1781193900)])
    monkeypatch.setattr(pinned, "fetch_event_by_slug", lambda slug: next(events))

    first = pinned.sync_pinned_series(
        conn, admin=None, pinned=[("btc-updown-5m", 300)], now=1781193601
    )
    second = pinned.sync_pinned_series(
        conn, admin=None, pinned=[("btc-updown-5m", 300)], now=1781193901
    )

    assert len(first) == 1 and len(second) == 1

    m1 = TableRead.read_market(conn, first[0].market_id)
    m2 = TableRead.read_market(conn, second[0].market_id)
    assert m1 is not None and m2 is not None
    assert m1.event_id is not None
    assert m1.event_id == m2.event_id  # one card for both windows

    event = TableRead.get_event_by_slug(conn, "btc-up-or-down-5m")
    assert event is not None
    assert event.polymarket_event_id == "10684"

    conn.close()
