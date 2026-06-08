"""Shared test-database helpers for the Postgres-backed suite.

Replaces the old `DbSession(':memory:')` / `sqlite3.connect(':memory:')`
fixtures. Tests run against a real local Postgres (`agentpit_test`); the
autouse fixture in conftest truncates every table before each test, so a
plain pool/connection on the shared test DB is already isolated.
"""

import os

import psycopg

from agentpit.db.row_factory import ci_dict_row
from agentpit.db.session import DbSession
from agentpit.db.table_create import TableCreate

TEST_DSN = os.environ.get("AGENTPIT_DATABASE_URL", "postgresql:///agentpit_test")


def fresh_test_db() -> DbSession:
    """A DbSession (psycopg pool) on the test database (schema ensured by
    __init__). Replaces `DbSession(':memory:')`."""
    return DbSession(TEST_DSN)


def fresh_test_conn() -> psycopg.Connection:
    """A raw psycopg connection on the test DB (autocommit + case-insensitive
    dict rows) with the schema ensured. Replaces
    `sqlite3.connect(':memory:')` DAL fixtures."""
    conn = psycopg.connect(TEST_DSN, autocommit=True, row_factory=ci_dict_row)
    TableCreate.create_all_tables(conn)
    return conn
