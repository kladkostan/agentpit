"""Valuing every trading account on a timer, so ranking never reads the chain."""
import logging

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.account_service import AccountService

log = logging.getLogger(__name__)


class LeaderboardService:
    """Writes one snapshot row per trading account per pass.

    Valuing an account walks its positions on chain, so this cannot happen on
    read: the Arena polls every four seconds, and pagination would not help --
    to know who belongs on page one you must value everyone.
    """

    def __init__(
        self,
        db: DbSession,
        onchain: OnchainAdmin,
        accounts: AccountService,
        settings: Settings,
    ):
        self._db = db
        self._onchain = onchain
        self._accounts = accounts
        self._settings = settings

    def _capital_raw(self, address: str) -> int:
        cash = self._onchain.usd_balance(address)
        rows = self._accounts.total_value(address)
        value_whole = rows[0]["value"] if rows else 0.0
        return cash + int(round(value_whole * 10**6))

    def take_snapshot(self, now: int) -> int:
        """Value every trading account. Returns the number of rows written.

        One account failing must not lose the whole pass -- a single unreadable
        position would otherwise cost every other account its data point.
        """
        with self._db.read() as conn:
            accounts = TableRead.list_traded_accounts(conn)

        written = 0
        for account in accounts:
            try:
                capital = self._capital_raw(account.eth_address)
            except Exception:
                log.exception("valuing %s failed", account.user_id)
                continue
            with self._db.write() as conn:
                deposited = TableRead.get_total_deposited(
                    conn, account.user_id, self._settings.paper_balance_target_raw
                )
                TableWrite.insert_account_snapshot(
                    conn, account.user_id, now, capital, deposited
                )
            written += 1
        return written
