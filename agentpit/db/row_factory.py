"""Case-insensitive dict row factory for psycopg.

Postgres folds unquoted identifiers to lowercase, so `SELECT MARKET_ID`
yields a column named `market_id`. The codebase accesses rows by the
upper-case names it wrote in the SQL (`r["MARKET_ID"]`) — matching the old
`sqlite3.Row` behaviour, which is case-insensitive. This factory returns a
dict whose lookups are case-insensitive, so every existing `r["COL"]`
access keeps working after the migration without rewriting column case.
"""

from typing import Any, Sequence

from psycopg import Cursor
from psycopg.rows import RowMaker


class CIDict(dict):
    """A dict with case-insensitive key access (keys stored as-returned)."""

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError:
            return super().__getitem__(key.lower())

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        return isinstance(key, str) and super().__contains__(key.lower())

    def get(self, key: str, default: Any = None) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        return super().get(key.lower(), default)


def ci_dict_row(cursor: Cursor) -> RowMaker:
    desc = cursor.description
    names = [c.name for c in desc] if desc else []

    def make_row(values: Sequence[Any]) -> CIDict:
        return CIDict(zip(names, values))

    return make_row
