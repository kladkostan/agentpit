"""Reduce Polymarket tag slugs to the categories the UI filters by.

Polymarket's own ``category`` field is dead — every market and every nested
event returns ``null``. The live taxonomy is ``tags[]``, a flat unordered list
mixing top-level categories ("Politics", "Crypto") with fine-grained topics
("Macron", "ETF", "GTA VI"). This module reduces that list to one category.
"""

from __future__ import annotations

from typing import Iterable

# Ordered strictest-first: a narrower category wins when a market carries
# several. "Politics" is last because Polymarket tags most geopolitics with it
# on top of the more specific "World" — 109 of 500 sampled markets, including
# every non-US election. Polymarket's own UI files those under World.
CATEGORY_PRIORITY: tuple[str, ...] = (
    "Sports",
    "Crypto",
    "Science",
    "Technology",
    "Pop Culture",
    "Business",
    "World",
    "Politics",
)

# Polymarket's top-level tag slugs. Values are normalised to the labels the UI
# expects, not the labels upstream returns: `pop-culture` is labelled "Culture"
# and `technology` is lowercase, and buildCategoryList() in MarketsPage.tsx
# would render either as a duplicate tab.
_CANONICAL_SLUGS: dict[str, str] = {
    "sports": "Sports",
    "crypto": "Crypto",
    "science": "Science",
    "technology": "Technology",
    "tech": "Technology",
    "pop-culture": "Pop Culture",
    "business": "Business",
    "world": "World",
    "politics": "Politics",
}

# Second-chance map for the ~5% of markets Polymarket never tagged with a
# top-level category — mostly geopolitics and macro. Recovers all but ~0.4%.
# Consulted only when no canonical tag matched.
_ALIAS_SLUGS: dict[str, str] = {
    "geopolitics": "World",
    "middle-east": "World",
    "war": "World",
    "elections": "Politics",
    "finance": "Business",
    "economy": "Business",
    "economic-policy": "Business",
    "fed": "Business",
    "earnings": "Business",
    "oil": "Business",
    "inflation": "Business",
    "weather": "Science",
    "pandemics": "Science",
    "health": "Science",
    "space": "Science",
    "ai": "Technology",
}

_UNRANKED = len(CATEGORY_PRIORITY)


def category_rank(category: str | None) -> int:
    """Position in ``CATEGORY_PRIORITY`` — lower is stricter.

    ``None`` and any value outside the tuple (e.g. a free-form category from
    ``POST /markets``) sort last, so a resolved category always outranks them.
    """
    if category is None:
        return _UNRANKED
    try:
        return CATEGORY_PRIORITY.index(category)
    except ValueError:
        return _UNRANKED


def _strictest(candidates: set[str]) -> str | None:
    if not candidates:
        return None
    return min(candidates, key=category_rank)


def resolve_category(tag_slugs: Iterable[str | None]) -> str | None:
    """Reduce a market's tag slugs to one category, or ``None``.

    Deterministic regardless of input order: Gamma returns ``tags[]`` unordered,
    so picking the first recognised slug would categorize the same market
    differently across sync passes.

    An exact canonical tag always beats an alias, even a stricter one — the
    alias map is a heuristic and must not override Polymarket's own labelling.
    """
    normalized = {s.strip().lower() for s in tag_slugs if s and s.strip()}
    canonical = {_CANONICAL_SLUGS[s] for s in normalized if s in _CANONICAL_SLUGS}
    if canonical:
        return _strictest(canonical)
    return _strictest({_ALIAS_SLUGS[s] for s in normalized if s in _ALIAS_SLUGS})
