"""How the events listing can be ordered, and the SQL each choice means.

This enum is the entire allow-list between a query string and an ORDER BY.
`sort` arrives from the caller, so nothing here interpolates it: `parse`
either returns a member or the default, and only members can produce SQL.

Every clause ends in `EVENT_ID DESC`. Without a unique tiebreak two events
with equal sort values can swap places between LIMIT/OFFSET pages, and the
reader sees one of them twice and the other never — the exact bug this whole
change exists to fix, reintroduced one level down.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar


class EventSort(str, Enum):
    """Values are the wire strings the UI sends."""

    VOLUME_24H = "volume24h"
    TOTAL_VOLUME = "totalVolume"
    LIQUIDITY = "liquidity"
    COMPETITIVE = "competitive"
    NEWEST = "newest"
    ENDING_SOON = "endingSoon"

    #: Assigned after the class body (see below) — an Enum treats a plain
    #: class attribute as another member, so DEFAULT cannot be given a value
    #: inside the class. An annotation with no value is not a member, so this
    #: only declares the attribute's type for the checker.
    DEFAULT: ClassVar["EventSort"]

    @classmethod
    def parse(cls, value: object) -> "EventSort":
        """A known wire value, else the default.

        Never raises: `sort` is caller-supplied, and a 500 on `?sort=nonsense`
        would let anyone take the home page down.
        """
        if not isinstance(value, str):
            return cls.DEFAULT
        wanted = value.strip().lower()
        for member in cls:
            if member.value.lower() == wanted:
                return member
        return cls.DEFAULT

    def order_by(self) -> str:
        """The clause to splice after the words ORDER BY.

        `NULLS LAST` on every leading column: an event we never captured a
        figure for belongs at the bottom of the list, never at the top of
        "Ending Soon".
        """
        return _ORDER_BY[self]


EventSort.DEFAULT = EventSort.VOLUME_24H

_ORDER_BY: "dict[EventSort, str]" = {
    # Unchanged, and pinned by tests/test_event_volume.py: this is what the
    # home page has ranked on since before sorting was a choice.
    EventSort.VOLUME_24H: "VOLUME_24HR DESC NULLS LAST, EVENT_ID DESC",
    EventSort.TOTAL_VOLUME: "VOLUME DESC NULLS LAST, EVENT_ID DESC",
    EventSort.LIQUIDITY: "LIQUIDITY DESC NULLS LAST, EVENT_ID DESC",
    EventSort.COMPETITIVE: "COMPETITIVE DESC NULLS LAST, EVENT_ID DESC",
    EventSort.NEWEST: "START_DATE DESC NULLS LAST, EVENT_ID DESC",
    EventSort.ENDING_SOON: "END_DATE ASC NULLS LAST, EVENT_ID DESC",
}
