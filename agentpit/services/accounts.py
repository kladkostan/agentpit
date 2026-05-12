from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import UserNotFoundError


def get_eth_address_for_api_key(db: DbSession, api_key: str) -> str:
    """Look up the eth address for an API key. Raises if no user matches.

    Anonymous user creation has been removed — every request must come from a
    registered, JWT-authenticated user.
    """
    with db.read() as conn:
        addr = TableRead.get_eth_address_for_api_key(conn, api_key)
    if addr is None:
        raise UserNotFoundError(f"no user for api_key {api_key!r}")
    return addr
