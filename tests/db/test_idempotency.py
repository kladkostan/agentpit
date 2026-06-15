"""idempotency_keys: a (api_key, client_order_id) claim is unique per user,
looks up its order id, and is purged by age."""

import psycopg
import pytest

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def test_claim_is_unique_and_looked_up():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k1", client_order_id="c1", order_id="0xaaa", created_at=100
        )
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k1", "c1") == "0xaaa"

    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.write() as conn:
            TableWrite.claim_idempotency_key(
                conn, api_key="k1", client_order_id="c1", order_id="0xbbb",
                created_at=200,
            )

    # Same client_order_id under a different api_key is independent.
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k2", client_order_id="c1", order_id="0xccc", created_at=100
        )
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k2", "c1") == "0xccc"


def test_get_idempotency_order_id_missing_returns_none():
    db = DbSession(Settings().database_url)
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "nope", "nope") is None


def test_purge_idempotency_keys_removes_old():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="old", order_id="0x1", created_at=100
        )
        TableWrite.claim_idempotency_key(
            conn, api_key="k", client_order_id="new", order_id="0x2", created_at=900
        )
        removed = TableWrite.purge_idempotency_keys(conn, before_ts=500)
    assert removed == 1
    with db.read() as conn:
        assert TableRead.get_idempotency_order_id(conn, "k", "old") is None
        assert TableRead.get_idempotency_order_id(conn, "k", "new") == "0x2"
