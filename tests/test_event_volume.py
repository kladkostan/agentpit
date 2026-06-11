"""Upstream 24h-volume capture, ordering, and serialization.

Covers the homepage-by-volume feature: events store an upstream `VOLUME_24HR`,
`list_events_with_markets` ranks by it (NULLS LAST), the sync extractors surface
it (per-event for trending, series-level for pinned), and the Gamma serializer
emits it.
"""

from agentpit.datastructures.event import Event
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.polymarket.gamma import to_gamma_event
from agentpit.polymarket.pinned import series_event_metadata
from agentpit.polymarket.polymarket_sync import _extract_event_metadata
from tests.db_helpers import fresh_test_conn


# ----- ordering ---------------------------------------------------------------


def test_events_ordered_by_volume_desc_nulls_last():
    conn = fresh_test_conn()
    a = TableWrite.upsert_event(conn, slug="a", title="A")
    TableWrite.upsert_event(conn, slug="b", title="B")  # stays NULL volume
    c = TableWrite.upsert_event(conn, slug="c", title="C")
    TableWrite.update_event_volume(conn, a.event_id, 100.0)
    # b stays NULL (never synced from upstream)
    TableWrite.update_event_volume(conn, c.event_id, 5000.0)

    pairs, total = TableRead.list_events_with_markets(conn, limit=10, offset=0)
    slugs = [ev.slug for ev, _ in pairs]

    assert total == 3
    assert slugs == ["c", "a", "b"]  # 5000, 100, then NULL last
    assert pairs[0][0].volume_24hr == 5000.0
    conn.close()


# ----- update_event_volume (the refresh seam) ---------------------------------


def test_update_event_volume_sets_value():
    conn = fresh_test_conn()
    e = TableWrite.upsert_event(conn, slug="x", title="X")
    TableWrite.update_event_volume(conn, e.event_id, 42.0)
    assert TableRead.get_event_by_slug(conn, "x").volume_24hr == 42.0
    conn.close()


def test_update_event_volume_noop_on_none_preserves_value():
    conn = fresh_test_conn()
    e = TableWrite.upsert_event(conn, slug="x", title="X")
    TableWrite.update_event_volume(conn, e.event_id, 42.0)
    TableWrite.update_event_volume(conn, e.event_id, None)  # must not clobber
    assert TableRead.get_event_by_slug(conn, "x").volume_24hr == 42.0
    conn.close()


# ----- capture: trending path -------------------------------------------------


def test_extract_event_metadata_pulls_volume24hr():
    meta = _extract_event_metadata(
        {"events": [{"id": "e", "slug": "s", "title": "T", "volume24hr": 7967.7}]}
    )
    assert meta is not None
    assert meta["volume_24hr"] == 7967.7


def test_extract_event_metadata_volume_none_when_absent():
    meta = _extract_event_metadata({"events": [{"id": "e", "slug": "s", "title": "T"}]})
    assert meta is not None
    assert meta["volume_24hr"] is None


# ----- capture: pinned-series path --------------------------------------------


def test_series_event_metadata_carries_volume24hr_through_extractor():
    event = {
        "series": [
            {
                "id": "10684",
                "slug": "btc-up-or-down-5m",
                "title": "BTC Up or Down 5m",
                "volume24hr": 14_646_954.7,
            }
        ]
    }
    entry = series_event_metadata(event)
    assert entry is not None
    assert entry["volume24hr"] == 14_646_954.7
    # And it flows through the shared extractor the bind path consumes.
    meta = _extract_event_metadata({"events": [entry]})
    assert meta is not None
    assert meta["volume_24hr"] == 14_646_954.7


# ----- serialization ----------------------------------------------------------


def test_to_gamma_event_emits_volume24hr():
    g = to_gamma_event(Event(event_id=1, slug="s", title="T", volume_24hr=12345.6), [])
    assert g.volume24hr == "12345.6"


def test_to_gamma_event_volume_zero_when_none():
    g = to_gamma_event(Event(event_id=1, slug="s", title="T"), [])
    assert g.volume24hr == "0"
