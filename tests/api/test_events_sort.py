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


# ----- the ?sort= parameter ---------------------------------------------------


def _slugs(client, query: str) -> "list[str]":
    return [e["slug"] for e in client.get(f"/events?limit=10&{query}").json()]


def test_sort_defaults_to_24h_volume(client):
    _seed({"lo": {"volume_24hr": 1.0}, "hi": {"volume_24hr": 99.0}})
    assert _slugs(client, "") == ["hi", "lo"]


def test_sort_by_liquidity(client):
    _seed(
        {
            "deep": {"volume_24hr": 1.0, "liquidity": 1_000_000.0},
            "thin": {"volume_24hr": 99.0, "liquidity": 1.0},
        }
    )
    # Opposed to the default sort, so a route that dropped the parameter fails.
    assert _slugs(client, "sort=liquidity") == ["deep", "thin"]
    assert _slugs(client, "") == ["thin", "deep"]


def test_sort_by_competitive_differs_from_liquidity(client):
    _seed(
        {
            "deep": {"liquidity": 1_000_000.0, "competitive": 0.1},
            "contested": {"liquidity": 1.0, "competitive": 0.99},
        }
    )
    assert _slugs(client, "sort=liquidity") == ["deep", "contested"]
    assert _slugs(client, "sort=competitive") == ["contested", "deep"]


def test_sort_by_ending_soon_is_ascending(client):
    _seed({"later": {"end_date": 9_000}, "sooner": {"end_date": 1_000}})
    assert _slugs(client, "sort=endingSoon") == ["sooner", "later"]


def test_an_unknown_sort_falls_back_instead_of_erroring(client):
    """`sort` is caller-supplied; a 500 here would let anyone take the home
    page down with a query string."""
    _seed({"lo": {"volume_24hr": 1.0}, "hi": {"volume_24hr": 99.0}})
    resp = client.get("/events?limit=10&sort=nonsense")
    assert resp.status_code == 200
    assert [e["slug"] for e in resp.json()] == ["hi", "lo"]


def test_the_cache_does_not_serve_one_sort_to_another(client):
    """The sort MUST be part of the cache key, or a liquidity-ordered page is
    served to a volume-ordered request for up to a whole TTL."""
    _seed(
        {
            "deep": {"volume_24hr": 1.0, "liquidity": 1_000_000.0},
            "thin": {"volume_24hr": 99.0, "liquidity": 1.0},
        }
    )
    assert _slugs(client, "sort=liquidity") == ["deep", "thin"]
    assert _slugs(client, "sort=volume24h") == ["thin", "deep"]


def test_sort_composes_with_a_tag_filter(client):
    _seed({"a": {"liquidity": 5.0}, "b": {"liquidity": 9.0}})
    resp = client.get("/events?limit=10&sort=liquidity&tag=nothing-matches-this")
    assert resp.status_code == 200
    assert resp.json() == []
