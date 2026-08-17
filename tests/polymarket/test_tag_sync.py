"""The sync's tag extraction and its do-not-clobber guard."""

from __future__ import annotations

from agentpit.polymarket.polymarket_sync import extract_tags


def test_extract_tags_returns_slug_label_pairs():
    pm = {"tags": [{"slug": "politics", "label": "Politics"}]}
    assert extract_tags(pm) == [("politics", "Politics")]


def test_extract_tags_normalises_the_slug_but_not_the_label():
    pm = {"tags": [{"slug": " Pop-Culture ", "label": "Culture"}]}
    assert extract_tags(pm) == [("pop-culture", "Culture")]


def test_extract_tags_falls_back_to_the_slug_when_the_label_is_missing():
    assert extract_tags({"tags": [{"slug": "iran"}]}) == [("iran", "iran")]
    assert extract_tags({"tags": [{"slug": "iran", "label": ""}]}) == [("iran", "iran")]
    assert extract_tags({"tags": [{"slug": "iran", "label": 7}]}) == [("iran", "iran")]


def test_extract_tags_returns_none_when_tags_is_absent_or_null():
    """The guard that matters. A Gamma request without include_tag=true comes
    back with tags: null; treating that as "no tags" would wipe good rows on
    every pass through such a code path."""
    assert extract_tags({}) is None
    assert extract_tags({"tags": None}) is None


def test_extract_tags_returns_none_when_tags_is_not_a_list():
    assert extract_tags({"tags": "politics"}) is None
    assert extract_tags({"tags": {"slug": "politics"}}) is None


def test_extract_tags_returns_empty_list_for_an_empty_upstream_list():
    """Distinct from None: upstream positively says this market has no tags."""
    assert extract_tags({"tags": []}) == []


def test_extract_tags_skips_malformed_entries_without_raising():
    """One bad entry must not stall the pass — a raise here would skip this
    market on every future sync, permanently."""
    pm = {
        "tags": [
            "not-a-dict",
            None,
            {"label": "No slug"},
            {"slug": None, "label": "Null slug"},
            {"slug": 42, "label": "Numeric slug"},
            {"slug": "   ", "label": "Blank slug"},
            {"slug": "iran", "label": "Iran"},
        ]
    }
    assert extract_tags(pm) == [("iran", "Iran")]
