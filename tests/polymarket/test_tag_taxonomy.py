"""Pure taxonomy rules: slug normalisation and the blocked-tag policy."""

from __future__ import annotations

from agentpit.polymarket.tag_taxonomy import (
    BLOCKED_SLUGS,
    MAX_FACET_COVERAGE,
    MAX_FACETS,
    MIN_NAV_EVENTS,
    NAV_SLUGS,
    is_blocked,
    normalize_slug,
)


def test_normalize_slug_lowercases_and_strips():
    # Gamma is inconsistent: the live crypto facet list contained a literal
    # "1H" beside lowercase siblings. Unnormalised, that splits one facet in two.
    assert normalize_slug("  1H ") == "1h"
    assert normalize_slug("Pop-Culture") == "pop-culture"


def test_normalize_slug_rejects_non_strings_and_blanks():
    assert normalize_slug(None) is None
    assert normalize_slug(123) is None
    assert normalize_slug("") is None
    assert normalize_slug("   ") is None


def test_is_blocked_covers_operational_tags():
    assert is_blocked("hide-from-new")
    assert is_blocked("recurring")
    assert is_blocked("up-or-down")


def test_is_blocked_matches_the_deprecated_prefix():
    assert is_blocked("deprec-us-election")
    assert not is_blocked("deprecation-policy")


def test_is_blocked_leaves_real_topics_alone():
    for slug in ("politics", "sports", "tennis", "games", "iran", "bitcoin"):
        assert not is_blocked(slug), slug


def test_games_is_not_blocklisted():
    # `games` is uninformative under `sports` (832 of 895 events), but the
    # coverage rule removes it there on the data. Under a parent where it is
    # genuinely selective it must survive.
    assert "games" not in BLOCKED_SLUGS


def test_nav_slugs_are_unique_normalised_and_ordered_politics_first():
    assert NAV_SLUGS[0] == "politics"
    assert len(set(NAV_SLUGS)) == len(NAV_SLUGS)
    for slug in NAV_SLUGS:
        assert normalize_slug(slug) == slug


def test_no_nav_slug_is_blocked():
    for slug in NAV_SLUGS:
        assert not is_blocked(slug), slug


def test_thresholds_have_the_agreed_values():
    assert MIN_NAV_EVENTS == 10
    assert MAX_FACET_COVERAGE == 0.9
    assert MAX_FACETS == 20
