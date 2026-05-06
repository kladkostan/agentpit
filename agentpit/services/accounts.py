from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def get_or_create_eth_address(db: DbSession, api_key: str) -> str:
    """Resolve the eth address for an api_key, creating an anonymous user if needed.

    Uses double-checked locking: the read lock fast path covers the common
    case (user already exists) without ever acquiring the write lock.
    """
    with db.read() as conn:
        existing = TableRead.get_eth_address_for_api_key(conn, api_key)
        if existing is not None:
            return existing
    with db.write() as conn:
        existing = TableRead.get_eth_address_for_api_key(conn, api_key)
        if existing is not None:
            return existing
        return TableWrite.create_anonymous_user_for_api_key(conn, api_key)
