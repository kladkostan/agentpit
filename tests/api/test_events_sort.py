"""GET /events: the two upstream metrics on the wire, and the ?sort= param."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentpit.api.main import app
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _seed(events: "dict[str, dict]") -> None:
    """`{slug: {volume_24hr, volume, liquidity, competitive, start_date, end_date}}`."""
    conn = fresh_test_conn()
    try:
        for slug, cols in events.items():
            ev = TableWrite.upsert_event(
                conn,
                slug=slug,
                title=slug.upper(),
                start_date=cols.get("start_date"),
                end_date=cols.get("end_date"),
            )
            TableWrite.update_event_volume(
                conn, ev.event_id, cols.get("volume_24hr"), cols.get("volume")
            )
            TableWrite.update_event_metrics(
                conn, ev.event_id, cols.get("liquidity"), cols.get("competitive")
            )
    finally:
        conn.close()


def test_the_wire_carries_both_metrics(client):
    _seed({"a": {"liquidity": 1976643.77, "competitive": 0.9846}})
    body = client.get("/events?limit=10").json()
    assert body[0]["liquidity"] == "1976643.77"
    assert body[0]["competitive"] == "0.9846"


def test_an_uncaptured_metric_serialises_as_zero_not_null(client):
    """Gamma's own convention, and the one `volume` already follows — the UI
    parses these with the same helper."""
    _seed({"a": {}})
    body = client.get("/events?limit=10").json()
    assert body[0]["liquidity"] == "0"
    assert body[0]["competitive"] == "0"
