import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from agentpit.db.table_create import TableCreate


class DbSession:
    """Owns the SQLite connection and serializes access to it.

    Use `read()` for read-only operations and `write()` for mutations. The
    `write()` context manager wraps the work in a SQLite transaction.

    Why a single exclusive mutex (not a reader/writer lock): the connection
    is shared across FastAPI worker threads, and SQLite connections are not
    safe for concurrent use across threads. `check_same_thread=False` only
    silences Python's safety check; it does not make sqlite3 internally
    thread-safe. Multiple threads invoking `.execute()` on one connection
    at the same time corrupts the connection's internal state and surfaces
    as ``sqlite3.InterfaceError: bad parameter or other API misuse`` (or,
    worse, silently wrong results). All access — reads and writes — must
    therefore serialize through the same lock.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
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
        with self._lock:
            self._ensure_connected()
            assert self._conn is not None
            yield self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._ensure_connected()
            assert self._conn is not None
            with self._conn:
                yield self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
