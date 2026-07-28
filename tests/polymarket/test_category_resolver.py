"""Unit tests for reducing Polymarket tag slugs to a single category."""

from __future__ import annotations

from agentpit.polymarket.category_resolver import (
    CATEGORY_PRIORITY,
    category_rank,
    resolve_category,
)


def test_resolves_exact_canonical_slug():
    assert resolve_category(["sports"]) == "Sports"
    assert resolve_category(["crypto"]) == "Crypto"
    assert resolve_category(["politics"]) == "Politics"


def test_normalises_upstream_labels_to_ui_names():
    """Upstream labels `pop-culture` "Culture" and `technology` lowercase.

    buildCategoryList() in MarketsPage.tsx matches on these exact strings and
    renders anything unrecognised as an extra tab.
    """
    assert resolve_category(["pop-culture"]) == "Pop Culture"
    assert resolve_category(["technology"]) == "Technology"
    assert resolve_category(["tech"]) == "Technology"


def test_priority_beats_input_order():
    """Gamma returns tags unordered, so the result must not depend on order."""
    assert resolve_category(["politics", "world"]) == "World"
    assert resolve_category(["world", "politics"]) == "World"


def test_canonical_tag_beats_higher_priority_alias():
    """`weather` aliases to Science (rank 2), `politics` is canonical (rank 7).

    The alias map is a heuristic and must never override Polymarket's own
    top-level labelling.
    """
    assert resolve_category(["politics", "weather"]) == "Politics"


def test_alias_pass_runs_only_when_no_canonical_tag_matched():
    assert resolve_category(["geopolitics", "iran", "trump-iran"]) == "World"
    assert resolve_category(["fed", "economy", "jerome-powell"]) == "Business"
    assert resolve_category(["weather", "daily-temperature"]) == "Science"


def test_alias_pass_also_honours_priority():
    """geopolitics -> World (rank 6), weather -> Science (rank 2)."""
    assert resolve_category(["geopolitics", "weather"]) == "Science"


def test_returns_none_when_nothing_matches():
    assert resolve_category([]) is None
    assert resolve_category(["macron", "resign", "gta-vi"]) is None


def test_ignores_empty_and_none_slugs():
    assert resolve_category([None, "", "   "]) is None
    assert resolve_category([None, "sports", ""]) == "Sports"


def test_slugs_are_case_and_whitespace_insensitive():
    assert resolve_category(["  SPORTS  "]) == "Sports"
    assert resolve_category(["Pop-Culture"]) == "Pop Culture"


def test_category_rank_orders_priority_strictest_first():
    ranks = [category_rank(c) for c in CATEGORY_PRIORITY]
    assert ranks == sorted(ranks)
    assert category_rank("Sports") < category_rank("Politics")


def test_category_rank_sinks_unknown_and_none_to_last():
    assert category_rank(None) == len(CATEGORY_PRIORITY)
    assert category_rank("Handmade Category") == len(CATEGORY_PRIORITY)
    assert category_rank("Politics") < category_rank(None)
