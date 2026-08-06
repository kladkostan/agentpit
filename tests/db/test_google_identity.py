"""users: a Google identity is a column, a unique index and two lookups."""

import psycopg
import pytest

from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


def test_creates_an_account_with_no_password():
    """A Google account has no password, and a sentinel would be a lie some
    later verify_password call could trip over."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn,
        email="nopass@example.com",
        password_hash=None,
        handle="NoPass",
        google_sub="sub-1",
    )
    assert TableRead.get_password_hash_by_userid(conn, user_id) is None
    conn.close()


def test_looks_an_account_up_by_google_sub():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn,
        email="sub@example.com",
        password_hash=None,
        handle="SubUser",
        google_sub="sub-42",
    )
    found = TableRead.get_user_by_google_sub(conn, "sub-42")
    assert found is not None and found.user_id == user_id
    assert TableRead.get_user_by_google_sub(conn, "sub-nobody") is None
    conn.close()


def test_google_sub_is_unique():
    conn = fresh_test_conn()
    TableWrite.create_user(
        conn, email="a@example.com", password_hash=None, handle="A", google_sub="dup"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        TableWrite.create_user(
            conn,
            email="b@example.com",
            password_hash=None,
            handle="B",
            google_sub="dup",
        )
    conn.close()


def test_many_accounts_may_have_no_google_sub():
    """NULLs do not collide — the unique index must not make Google mandatory."""
    conn = fresh_test_conn()
    TableWrite.create_user(conn, email="p1@example.com", password_hash="x", handle="P1")
    TableWrite.create_user(conn, email="p2@example.com", password_hash="x", handle="P2")
    assert TableRead.get_user_by_google_sub(conn, "anything") is None
    conn.close()


def test_stamps_a_google_sub_on_an_existing_account():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="link@example.com", password_hash="x", handle="Link"
    )
    assert TableWrite.set_google_sub(conn, user_id, "sub-linked") is True
    found = TableRead.get_user_by_google_sub(conn, "sub-linked")
    assert found is not None and found.user_id == user_id
    conn.close()


def test_email_lookup_for_linking_ignores_case():
    """Registration stores the address as typed. `Alice@Example.com` and the
    `alice@example.com` Google reports are the same person to everyone except
    `=`, and linking is the one place that difference would mint a second
    wallet."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="Alice@Example.COM", password_hash="x", handle="Alice"
    )
    found = TableRead.get_user_by_email_ci(conn, "alice@example.com")
    assert found is not None and found.user_id == user_id
    # The exact-match reader is unchanged — login still compares as stored.
    assert TableRead.get_user_by_email(conn, "alice@example.com") is None
    conn.close()


def test_email_lookup_returns_none_for_a_stranger():
    conn = fresh_test_conn()
    assert TableRead.get_user_by_email_ci(conn, "nobody@example.com") is None
    conn.close()
