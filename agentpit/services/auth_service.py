import logging

from agentpit.auth.jwt import JwtCoder
from agentpit.auth.passwords import hash_password, verify_password
from agentpit.config import Settings
from agentpit.datastructures.auth_response import AuthResponse, UserPublic
from agentpit.datastructures.login_request import LoginRequest
from agentpit.datastructures.register_request import RegisterRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import (
    InvalidCredentialsError,
    OnboardingError,
    UserAlreadyExistsError,
)
from agentpit.onchain.admin import OnchainAdmin

log = logging.getLogger(__name__)


class AuthService:
    """Coordinates registration, login, and on-chain onboarding.

    `onchain_admin` may be None for tests / dev modes where the chain isn't
    reachable (`AGENTPIT_ONCHAIN_DISABLED=true`); in that case onboarding is
    skipped and `ONBOARDED_AT` stays NULL.
    """

    def __init__(
        self,
        db: DbSession,
        coder: JwtCoder,
        onchain_admin: OnchainAdmin | None,
        settings: Settings,
    ):
        self._db = db
        self._coder = coder
        self._onchain = onchain_admin
        self._settings = settings

    def register(self, payload: RegisterRequest) -> AuthResponse:
        with self._db.write() as conn:
            if TableRead.get_user_by_email(conn, payload.email) is not None:
                raise UserAlreadyExistsError(payload.email)
            password_hash = hash_password(payload.password)
            user_id, acct, _api_key = TableWrite.create_user(
                conn,
                email=payload.email,
                password_hash=password_hash,
                handle=payload.handle,
            )

        # On-chain onboarding happens *outside* the DB transaction so we don't
        # hold the write lock for ~1s of network round-trips.
        if self._onchain is not None:
            try:
                self._run_onboarding(acct)
            except Exception as exc:
                log.exception("on-chain onboarding failed for user %s", user_id)
                raise OnboardingError(str(exc)) from exc
            with self._db.write() as conn:
                TableWrite.mark_user_onboarded(conn, user_id)
        else:
            log.warning(
                "AGENTPIT_ONCHAIN_DISABLED is set — skipping faucet drip + approvals"
            )

        with self._db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise RuntimeError("user disappeared between insert and read")
        return self._issue(user)

    def login(self, payload: LoginRequest) -> AuthResponse:
        with self._db.read() as conn:
            password_hash = TableRead.get_password_hash_by_email(conn, payload.email)
            user = (
                TableRead.get_user_by_email(conn, payload.email)
                if password_hash is not None
                else None
            )
        if password_hash is None or user is None:
            raise InvalidCredentialsError("invalid email or password")
        if not verify_password(payload.password, password_hash):
            raise InvalidCredentialsError("invalid email or password")
        return self._issue(user)

    # --- helpers --------------------------------------------------------

    def _run_onboarding(self, user_account) -> None:
        assert self._onchain is not None
        timeout = self._settings.tx_confirmations_timeout_s
        self._onchain.fund_gas(
            user_account.address,
            self._settings.signup_gas_grant_wei,
            timeout=timeout,
        )
        self._onchain.faucet_drip(user_account.address, timeout=timeout)
        self._onchain.grant_user_approvals(user_account, timeout=timeout)

    def _issue(self, user: User) -> AuthResponse:
        token = self._coder.encode(user_id=user.user_id, email=user.email)
        return AuthResponse(
            access_token=token,
            user=UserPublic(
                user_id=user.user_id,
                email=user.email,
                handle=user.handle,
                eth_address=user.eth_address,
                onboarded_at=user.onboarded_at,
                created_at=user.created_at,
            ),
        )
