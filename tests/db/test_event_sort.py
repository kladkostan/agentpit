"""The sort enum is the only place a caller-supplied string becomes SQL."""

from __future__ import annotations

import pytest

from agentpit.datastructures.event_sort import EventSort


def test_wire_values_match_what_the_ui_sends():
    assert [s.value for s in EventSort] == [
        "volume24h",
        "totalVolume",
        "liquidity",
        "competitive",
        "newest",
        "endingSoon",
    ]


def test_the_default_is_24h_volume():
    # The home page has ranked on this since before sorting existed; changing
    # it would silently reorder everyone's first screen.
    assert EventSort.DEFAULT is EventSort.VOLUME_24H


def test_parse_accepts_a_known_wire_value():
    assert EventSort.parse("liquidity") is EventSort.LIQUIDITY
    assert EventSort.parse("endingSoon") is EventSort.ENDING_SOON


def test_parse_falls_back_rather_than_raising():
    """`sort` is caller-supplied. A 500 on `?sort=nonsense` would let anyone
    take the listing down, and an exception here would reach the home page."""
    for junk in ["nonsense", "", "  ", None, 7, "DROP TABLE events"]:
        assert EventSort.parse(junk) is EventSort.DEFAULT


def test_parse_is_case_and_whitespace_tolerant():
    assert EventSort.parse(" Liquidity ") is EventSort.LIQUIDITY
    assert EventSort.parse("ENDINGSOON") is EventSort.ENDING_SOON


def test_the_default_order_by_is_unchanged():
    """Pinned verbatim: two existing tests depend on this exact clause."""
    assert (
        EventSort.VOLUME_24H.order_by()
        == "VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC"
    )


def test_every_order_by_ends_with_the_unique_tiebreak():
    """Without it, two events with equal sort values can swap between LIMIT
    pages — one gets shown twice and another never at all."""
    for sort in EventSort:
        assert sort.order_by().endswith("EVENT_ID DESC"), sort


def test_every_order_by_puts_missing_values_last():
    """An event we never captured a figure for belongs at the bottom, not at
    the top of "Ending Soon"."""
    for sort in EventSort:
        head = sort.order_by().split(",")[0]
        assert "NULLS LAST" in head, sort


def test_ending_soon_is_the_only_ascending_sort():
    assert EventSort.ENDING_SOON.order_by().startswith("END_DATE ASC")
    for sort in EventSort:
        if sort is not EventSort.ENDING_SOON:
            assert " ASC" not in sort.order_by().split(",")[0], sort


def test_each_sort_uses_its_own_column():
    columns = {sort: sort.order_by().split()[0] for sort in EventSort}
    assert columns[EventSort.VOLUME_24H] == "VOLUME_24HR"
    assert columns[EventSort.TOTAL_VOLUME] == "VOLUME"
    assert columns[EventSort.LIQUIDITY] == "LIQUIDITY"
    assert columns[EventSort.COMPETITIVE] == "COMPETITIVE"
    assert columns[EventSort.NEWEST] == "START_DATE"
    assert columns[EventSort.ENDING_SOON] == "END_DATE"
    # Liquidity and Competitive were the same sort before this existed.
    assert len(set(columns.values())) == len(EventSort)


def test_order_by_contains_no_caller_supplied_text():
    """The enum is the whole allow-list. Nothing a caller sends reaches SQL."""
    assert EventSort.parse("VOLUME_24HR; DROP TABLE events").order_by() == (
        EventSort.DEFAULT.order_by()
    )


@pytest.mark.parametrize("sort", list(EventSort))
def test_order_by_is_a_bare_clause(sort: EventSort):
    """Callers splice this after the words ORDER BY; a leading keyword or a
    trailing semicolon would break the query they build."""
    clause = sort.order_by()
    assert not clause.upper().startswith("ORDER BY")
    assert ";" not in clause
