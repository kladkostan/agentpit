"""Idempotent provisioning of the engine's house (bot) accounts."""
import logging

from agentpit.auth.passwords import hash_password
from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin

log = logging.getLogger(__name__)

_EMAIL = "house-bot-{i}@agentpit.local"
_PASSWORD = "house-bot-fixed-secret-pw"  # house accounts never log in via HTTP


def email_for(i: int) -> str:
    """Deterministic house-account email; index 0 is the mirror account."""
    return _EMAIL.format(i=i)


class HouseAccountProvisioner:
    def __init__(self, db: DbSession, onchain: OnchainAdmin, settings: Settings):
        self._db = db
        self._onchain = onchain
        self._settings = settings

    def ensure_provisioned(self) -> list[User]:
        target = self._settings.liquidity_house_account_count
        with self._db.read() as conn:
            existing = {u.email: u for u in TableRead.list_bot_users(conn)}

        for u in existing.values():           # re-onboard accounts the chain forgot
            self._maybe_reonboard(u)

        users: list[User] = list(existing.values())
        for i in range(target):
            email = email_for(i)
            if email in existing:
                continue
            users.append(self._create_and_onboard(email))
        log.info("house accounts: %d provisioned (target %d)", len(users), target)
        return users

    def _create_and_onboard(self, email: str) -> User:
        with self._db.write() as conn:
            prior = TableRead.get_user_by_email(conn, email)
            if prior is not None:             # partial-create recovery
                user_id, acct, api_key = prior.user_id, prior.eth_key, prior.api_key
            else:
                user_id, acct, api_key = TableWrite.create_user(
                    conn, email=email, password_hash=hash_password(_PASSWORD), handle=None
                )
        self._fund(acct)
        with self._db.write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)
            TableWrite.mark_user_as_bot(conn, api_key)
        with self._db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        assert user is not None
        return user

    def _fund(self, acct) -> None:
        timeout = self._settings.tx_confirmations_timeout_s
        for _ in range(self._settings.liquidity_funding_drips):
            self._onchain.faucet_drip(acct.address, timeout=timeout)
        self._onchain.fund_gas(
            acct.address, self._settings.signup_gas_grant_wei, timeout=timeout
        )
        self._onchain.grant_user_approvals(acct, timeout=timeout)

    def _maybe_reonboard(self, user: User) -> None:
        try:
            if self._onchain.native_balance(user.eth_address) > 0:
                return
        except Exception as exc:
            log.warning("native balance check failed for %s: %s", user.user_id, exc)
            return
        log.info("house account %s unfunded (chain reset) — re-onboarding", user.email)
        try:
            self._fund(user.eth_key)
        except Exception:
            log.exception("re-onboarding house account %s failed", user.email)
