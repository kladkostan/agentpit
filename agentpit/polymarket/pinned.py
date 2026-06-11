"""Pinned recurring-series sync.

Top-N-by-volume sync cannot capture high-frequency recurring markets (e.g.
*BTC Up or Down 5m*): a single live window has tiny volume while tradeable and
only accumulates volume after it closes. This module pins such series by config
and force-syncs the CURRENT live window of each, grouping every window under one
agentpit event (the series), reusing the existing creation + event-binding path.

See docs/superpowers/specs/2026-06-11-pinned-series-sync-design.md.
"""

import logging

from py_clob_client.http_helpers.helpers import get

from agentpit.datastructures.market import Market
from agentpit.polymarket.polymarket_sync import (
    POLYMARKET_GAMMA_URL,
    _normalize_market_fields,
    create_polymarket_markets_if_needed,
)

logger = logging.getLogger(__name__)


def parse_pinned_series(raw: str) -> list[tuple[str, int]]:
    """Parse ``"base:interval,base:interval"`` into ``[(base, interval), ...]``.

    Malformed entries (missing colon, non-int interval, non-positive interval, empty)
    are skipped with a warning rather than failing the whole config.
    """
    out: list[tuple[str, int]] = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        base, sep, interval_raw = entry.rpartition(":")
        base = base.strip()
        if not sep or not base:
            logger.warning("pinned-series: skipping malformed entry %r", entry)
            continue
        try:
            interval = int(interval_raw.strip())
        except ValueError:
            logger.warning("pinned-series: skipping non-int interval in %r", entry)
            continue
        if interval <= 0:
            logger.warning("pinned-series: skipping non-positive interval in %r", entry)
            continue
        out.append((base, interval))
    return out


def current_window_slug(base: str, interval: int, now: int) -> str:
    """Exact event slug of the window live at ``now`` (grid-aligned)."""
    return f"{base}-{now - (now % interval)}"


def next_wake_delay(now: int, align_interval: int, offset: int) -> float:
    """Seconds until the next ``align_interval`` boundary plus ``offset``.

    Recomputed from the current time each call, so a slow cycle that overruns a
    boundary simply targets the next one — no drift, never negative.
    """
    return float(((now // align_interval + 1) * align_interval + offset) - now)


def fetch_event_by_slug(slug: str) -> dict | None:
    """Fetch a single Gamma event by slug; first element or ``None``."""
    result = get(f"{POLYMARKET_GAMMA_URL}/events?slug={slug}")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return None


def _event_entry(src: dict) -> dict | None:
    """Build an ``events[]``-array entry (the shape `_extract_event_metadata`
    consumes) from an event-or-series dict. ``None`` if slug/title are missing.
    """
    slug = src.get("slug")
    title = src.get("title") or src.get("name")
    if not slug or not title:
        return None
    return {
        "id": src.get("id"),
        "slug": str(slug),
        "title": str(title),
        "description": src.get("description") or "",
        "image": src.get("image") or src.get("icon") or None,
        "icon": src.get("icon") or src.get("image") or None,
        "category": src.get("category"),
        "startDate": src.get("startDate") or src.get("startDateIso"),
        "endDate": src.get("endDate") or src.get("endDateIso"),
    }


def series_event_metadata(event: dict) -> dict | None:
    """Build a series-level ``events[]`` entry from ``event["series"][0]``.

    Using the SERIES id/slug/title (stable across windows) — not the per-window
    event — is what groups every window under one agentpit event. ``None`` when
    the event has no usable ``series``.
    """
    series = event.get("series")
    if not isinstance(series, list) or not series or not isinstance(series[0], dict):
        return None
    return _event_entry(series[0])
