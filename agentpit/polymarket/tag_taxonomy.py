"""Which Polymarket tags the UI navigates by, and which it ignores.

Gamma returns a flat unordered ``tags[]`` per market — roughly 4.6 of them,
drawn from a catalogue of 759 across our own event set. Most are real topics
("Trump", "Bitcoin", "Strait of Hormuz"); a minority describe how a market is
scheduled or settled rather than what it is about. This module holds the
editorial judgement about which is which, so the DAL and the API stay
mechanical.
"""

from __future__ import annotations

# The top-level navigation, in display order. This is an ALLOW list, not a
# ranking hint: a slug absent here never becomes a category. It is also only
# half the rule — a slug listed here still renders only when the database
# actually holds MIN_NAV_EVENTS events carrying it, so a tab can never lead to
# an empty grid.
#
# Ordering is editorial and mirrors Polymarket's own row, which is likewise not
# sorted by size (they lead with Politics though Sports is three times larger).
NAV_SLUGS: tuple[str, ...] = (
    "politics",
    "sports",
    "crypto",
    "elections",
    "geopolitics",
    "tennis",
    "esports",
    "soccer",
    "weather",
    "tech",
    "pop-culture",
    "finance",
    "economy",
    "world",
    "ai",
    "business",
    # `science` is deliberately absent. It clears MIN_NAV_EVENTS (11 events on
    # 2026-08-07) but the sidebar is a vertical list, and at seventeen entries
    # it stopped fitting on screen. The smallest category is the one to drop.
    # Its markets are still reachable: most also carry weather, health or
    # space, which are facets under their own parents.
)

# Operational tags: they describe a market's cadence, its settlement mechanic
# or its visibility in Polymarket's own UI, and tell a reader nothing about the
# subject. `hide-from-new` alone sits on 236 of our events.
#
# `games` is deliberately NOT here. It is uninformative under `sports` (832 of
# 895 events) but MAX_FACET_COVERAGE removes it there on the data rather than on
# a hunch, and under a parent where it is genuinely selective it should survive.
BLOCKED_SLUGS: frozenset[str] = frozenset(
    {
        # cadence
        "recurring",
        "daily",
        "weekly",
        "monthly",
        "yearly",
        "hourly",
        "1h",
        "4h",
        "today",
        "extended",
        # settlement mechanics
        "up-or-down",
        "hit-price",
        "multi-strikes",
        "price-milestone",
        "neg-risk",
        # upstream UI plumbing
        "hide-from-new",
        "new",
        "trending",
        "all",
        "main-election",
        "earn-4",
    }
)

# Polymarket retires a tag by renaming it rather than deleting it, leaving
# rows like `deprec-us-election` in the live feed.
DEPRECATED_PREFIX = "deprec-"

# A top-level entry below this many events is hidden rather than rendered as a
# near-empty tab. It is the floor, not the editorial choice: a slug can also be
# left out of NAV_SLUGS entirely, which is what happened to `science`.
MIN_NAV_EVENTS = 10

# A facet matching more than this share of its parent says nothing — it is the
# parent under another name. Removes `games` from `sports` (832 of 895).
MAX_FACET_COVERAGE = 0.9

# Longest subcategory list we will render under one category.
MAX_FACETS = 20


def normalize_slug(value: object) -> str | None:
    """Lowercase and strip a tag slug, or return None if it is not usable.

    Non-strings are rejected rather than coerced: Gamma has been observed
    returning nulls inside ``tags[]``, and ``str(None)`` would silently invent
    a tag called "none".
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def is_blocked(slug: str) -> bool:
    """True when a slug must never be shown as a category or a facet."""
    return slug in BLOCKED_SLUGS or slug.startswith(DEPRECATED_PREFIX)
