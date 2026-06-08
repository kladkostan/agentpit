from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

from agentpit.db.row_factory import ci_dict_row
from agentpit.db.table_create import TableCreate


class DbSession:
    """Owns a psycopg connection pool. `read()`/`write()` each check out a
    pooled connection; psycopg's connection context commits on clean exit and
    rolls back on exception. No global mutex — the pool gives each thread its
    own connection, so reads and writes run concurrently.
    """

    def __init__(self, dsn: str, *, min_size: int = 2, max_size: int = 16):
        self._pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": ci_dict_row, "autocommit": False},
            open=True,
        )
        with self._pool.connection() as conn:
            TableCreate.create_all_tables(conn)

    @contextmanager
    def read(self) -> Iterator[psycopg.Connection]:
        with self._pool.connection() as conn:
            yield conn

    @contextmanager
    def write(self) -> Iterator[psycopg.Connection]:
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self._pool.close()
