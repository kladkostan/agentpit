import sqlite3
from contextlib import contextmanager
from typing import Iterator

from fasteners import ReaderWriterLock

from agentpit.db.table_create import TableCreate


class DbSession:
    """Owns the SQLite connection and the read/write lock that guards it.

    Use `read()` for read-only operations and `write()` for mutations. The
    `write()` context manager wraps the work in a SQLite transaction.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = ReaderWriterLock()
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        TableCreate.create_all_tables(self._conn)

    def _ensure_connected(self) -> None:
        if self._conn is None:
            self._connect()
            return
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            self._connect()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock.read_lock():
            self._ensure_connected()
            assert self._conn is not None
            yield self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock.write_lock():
            self._ensure_connected()
            assert self._conn is not None
            with self._conn:
                yield self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
