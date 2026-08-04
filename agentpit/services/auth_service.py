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
    BusinessRuleError,
    InvalidCredentialsError,
    OnboardingError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from agentpit.onchain.admin import OnchainAdmin

log = logging.getLogger(__name__)


class AuthService:
    """Coordinates registration, login, and on-chain onboarding."""

    def __init__(
        self,
        db: DbSession,
        coder: JwtCoder,
        onchain_admin: OnchainAdmin,
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
        try:
            self._run_onboarding(acct)
        except Exception as exc:
            log.exception("on-chain onboarding failed for user %s", user_id)
            raise OnboardingError(str(exc)) from exc
        with self._db.write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)

        # Recording the deposit is a separate transaction from marking the
        # user onboarded above. If it fails -- whether the chain read or the
        # UPDATE itself raises -- psycopg would otherwise issue COMMIT on an
        # already-aborted transaction and Postgres turns that into a
        # ROLLBACK, taking mark_user_onboarded down with it. A failure here
        # must not turn a successful signup into a failed one (same treatment
        # on-chain reads get elsewhere in this service -- see
        # _maybe_reonboard), and TOTAL_DEPOSITED staying NULL is fine: it
        # reads back as the grant via get_total_deposited's default.
        try:
            # Read the granted amount off the chain rather than from config:
            # the grant is baked into an immutable contract by
            # scripts/deploy_exchange.sh, while paper_balance_target_raw is a
            # separate Settings field. They are documented to agree and today
            # they do, but they are two sources and either can move.
            #
            # Read before opening the transaction, for the same reason the
            # onboarding above sits outside one: no DB write lock should be
            # held across a network round-trip.
            granted = self._onchain.usd_balance(acct.address)
            with self._db.write() as conn:
                TableWrite.set_total_deposited(conn, user_id, granted)
                TableWrite.set_deployment_id(
                    conn, user_id, self._onchain.deployment_id
                )
        except Exception:
            log.exception("reading granted balance failed for user %s", user_id)

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
        self._maybe_reonboard(user)
        return self._issue(user)

    def change_password(
        self,
        *,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> None:
        with self._db.write() as conn:
            current_hash = TableRead.get_password_hash_by_userid(conn, user_id)
            if current_hash is None:
                raise UserNotFoundError()
            if not verify_password(current_password, current_hash):
                raise InvalidCredentialsError("invalid current password")
            if verify_password(new_password, current_hash):
                raise BusinessRuleError(
                    "new password must be different from current password"
                )

            updated = TableWrite.update_user_password_hash(
                conn, user_id, hash_password(new_password)
            )
            if not updated:
                raise UserNotFoundError()

    # --- helpers --------------------------------------------------------

    def _run_onboarding(self, user_account) -> None:
        timeout = self._settings.tx_confirmations_timeout_s
        self._onchain.fund_gas(
            user_account.address,
            self._settings.signup_gas_grant_wei,
            timeout=timeout,
        )
        self._onchain.faucet_drip(user_account.address, timeout=timeout)
        self._onchain.grant_user_approvals(user_account, timeout=timeout)

    def _maybe_reonboard(self, user: User) -> None:
        """Re-run onboarding for an already-onboarded user with zero native balance.

        Anvil's chain state is wiped on every restart while the DB persists, so a
        user can end up logged in but unfunded. Native balance is the chain-wipe
        signal: on a chain that gets reset it never drops to zero through normal
        use (gas spent per tx is tiny relative to signup_gas_grant_wei). Failures
        here are logged but never block login — the user can still authenticate
        and see balance errors at trade time.

        That reading only holds while the chain is disposable. On a durable chain
        a zero balance means the account spent its gas, and re-granting on login
        would be a treasury faucet anyone could drain on repeat, so
        `simulated_chain=False` turns this off and the signup grant becomes once
        per account. (The house account does not rely on this path at all — it is
        kept above a gas floor by the mirror's top-up loop.)
        """
        if not self._settings.simulated_chain:
            return
        if self._onchain is None or user.onboarded_at is None:
            return
        try:
            native = self._onchain.native_balance(user.eth_address)
        except Exception as exc:
            log.warning("chain balance check failed for %s: %s", user.user_id, exc)
            return
        if native > 0:
            return
        log.info(
            "user %s has zero native balance — re-running onboarding "
            "(chain likely reset)",
            user.user_id,
        )
        try:
            self._run_onboarding(user.eth_key)
        except Exception:
            log.exception("re-onboarding failed for %s", user.user_id)
            return

        # A wipe means the account is starting over: overwrite (not add to)
        # TOTAL_DEPOSITED, or every historical top-up before the wipe would
        # still count as deposited against grant-level post-wipe capital and
        # `earned = capital - deposited` would read deeply negative. Read the
        # balance only after `_run_onboarding` succeeded, so a failed
        # reonboard never resets the figure for an account still on its old
        # grant. Own transaction and swallowed failure, same as the deposit
        # write in register() and for the same reason: this path must keep
        # never blocking login, and a failure here just leaves
        # TOTAL_DEPOSITED at its prior value rather than corrupting it.
        #
        # Record the identity in the same write, exactly as register() does.
        # Without it the row keeps the stale identity even though the deposit
        # was just corrected, so the next top_up finds seen != current and
        # resets the ledger it was just handed back.
        try:
            with self._db.write() as conn:
                TableWrite.set_total_deposited(
                    conn, user.user_id, self._onchain.usd_balance(user.eth_address)
                )
                TableWrite.set_deployment_id(
                    conn, user.user_id, self._onchain.deployment_id
                )
        except Exception:
            log.exception(
                "resetting deposited balance failed for %s", user.user_id
            )

    def _issue(self, user: User) -> AuthResponse:
        token = self._coder.encode(user_id=user.user_id, email=user.email)
        return AuthResponse(
            access_token=token,
            user=UserPublic(
                user_id=user.user_id,
                email=user.email,
                handle=user.handle,
                eth_address=user.eth_address,
                api_key=user.api_key,
                onboarded_at=user.onboarded_at,
                created_at=user.created_at,
            ),
        )
