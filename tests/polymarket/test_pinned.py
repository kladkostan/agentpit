import agentpit.polymarket.pinned as pinned
from agentpit.polymarket.pinned import (
    current_window_slug,
    fetch_event_by_slug,
    next_wake_delay,
    parse_pinned_series,
    series_event_metadata,
)


# ----- parse_pinned_series ----------------------------------------------------

def test_parse_pinned_series_single():
    assert parse_pinned_series("btc-updown-5m:300") == [("btc-updown-5m", 300)]


def test_parse_pinned_series_multiple_and_whitespace():
    raw = " btc-updown-5m:300 , eth-updown-5m:900 "
    assert parse_pinned_series(raw) == [
        ("btc-updown-5m", 300),
        ("eth-updown-5m", 900),
    ]


def test_parse_pinned_series_skips_malformed():
    # missing colon, non-int interval, non-positive interval, empty entries
    raw = "btc-updown-5m:300,no-colon,eth-updown-5m:abc,x:0,,sol-updown-15m:900"
    assert parse_pinned_series(raw) == [
        ("btc-updown-5m", 300),
        ("sol-updown-15m", 900),
    ]


def test_parse_pinned_series_empty():
    assert parse_pinned_series("") == []
    assert parse_pinned_series("   ") == []


# ----- current_window_slug ----------------------------------------------------

def test_current_window_slug_grid_math():
    # 1781193601 is 1s past the 1781193600 boundary (a multiple of 300).
    assert (
        current_window_slug("btc-updown-5m", 300, 1781193601)
        == "btc-updown-5m-1781193600"
    )


def test_current_window_slug_exact_boundary():
    assert (
        current_window_slug("btc-updown-5m", 300, 1781193600)
        == "btc-updown-5m-1781193600"
    )


# ----- next_wake_delay --------------------------------------------------------

def test_next_wake_delay_mid_window():
    # 5s past a boundary, align 300, offset 10 -> wake at next boundary + 10.
    assert next_wake_delay(1781193605, 300, 10) == 305.0


def test_next_wake_delay_on_boundary_waits_full_interval():
    # Exactly on a boundary -> next boundary is a full interval away (+offset).
    assert next_wake_delay(1781193600, 300, 10) == 310.0


def test_next_wake_delay_recomputes_no_drift():
    # An overrun that lands just before the next boundary still schedules the
    # NEXT boundary, not a negative/zero delay.
    assert next_wake_delay(1781193899, 300, 10) == 11.0


# ----- series_event_metadata --------------------------------------------------

def test_series_event_metadata_extracts_series_entry():
    event = {
        "id": "580480",
        "slug": "btc-updown-5m-1781193600",
        "title": "Bitcoin Up or Down - June 11, 12:00PM-12:05PM ET",
        "series": [
            {
                "id": "10684",
                "slug": "btc-up-or-down-5m",
                "title": "BTC Up or Down 5m",
                "image": "",
                "icon": "",
                "category": None,
            }
        ],
    }
    meta = series_event_metadata(event)
    assert meta is not None
    # Series id/slug/title — NOT the per-window 580480 / window slug.
    assert meta["id"] == "10684"
    assert meta["slug"] == "btc-up-or-down-5m"
    assert meta["title"] == "BTC Up or Down 5m"


def test_series_event_metadata_none_when_no_series():
    assert series_event_metadata({"id": "1", "slug": "s", "title": "T"}) is None
    assert series_event_metadata({"series": []}) is None


# ----- fetch_event_by_slug ----------------------------------------------------

def test_fetch_event_by_slug_returns_first(monkeypatch):
    monkeypatch.setattr(pinned, "get", lambda url: [{"slug": "s", "title": "T"}])
    assert fetch_event_by_slug("s") == {"slug": "s", "title": "T"}


def test_fetch_event_by_slug_none_on_empty(monkeypatch):
    monkeypatch.setattr(pinned, "get", lambda url: [])
    assert fetch_event_by_slug("s") is None
