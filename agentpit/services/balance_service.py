"""Restoring a user's paper balance to the target, at most once a day."""
from pydantic import BaseModel

from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin


class TopUpResult(BaseModel):
    balance_raw: int
    minted_raw: int
    next_allowed_at: int


def topup_amount_raw(balance_raw: int, target_raw: int) -> int:
    """How much to mint so the account lands exactly on the target.

    Zero when the balance is already there or beyond: this restores a demo
    balance, it does not hand out a fixed sum. A flat grant would pay more to
    someone who lost everything than to someone who did well.
    """
    return max(0, target_raw - balance_raw)


def next_allowed_at(last_topup_at: int | None, cooldown_seconds: int) -> int:
    """Unix time when the next top-up becomes allowed; 0 when it already is."""
    if last_topup_at is None:
        return 0
    return last_topup_at + cooldown_seconds


class BalanceService:
    def __init__(self, db: DbSession, onchain: OnchainAdmin, settings: Settings):
        self._db = db
        self._onchain = onchain
        self._settings = settings

    def top_up(self, user: User, now: int) -> TopUpResult:
        with self._db.read() as conn:
            last = TableRead.get_last_topup_at(conn, user.user_id)

        allowed_at = next_allowed_at(last, self._settings.topup_cooldown_seconds)
        balance = self._onchain.usd_balance(user.eth_address)
        if now < allowed_at:
            return TopUpResult(
                balance_raw=balance, minted_raw=0, next_allowed_at=allowed_at
            )

        minted = topup_amount_raw(balance, self._settings.paper_balance_target_raw)
        if minted == 0:
            # Nothing to restore. Not a failure, and it must not start the
            # cooldown — otherwise checking while ahead costs you the day.
            return TopUpResult(
                balance_raw=balance, minted_raw=0, next_allowed_at=allowed_at
            )

        self._onchain.mint_to(
            user.eth_address,
            minted,
            timeout=self._settings.tx_confirmations_timeout_s,
        )
        with self._db.write() as conn:
            TableWrite.set_last_topup_at(conn, user.user_id, now)
        return TopUpResult(
            balance_raw=balance + minted,
            minted_raw=minted,
            next_allowed_at=now + self._settings.topup_cooldown_seconds,
        )
