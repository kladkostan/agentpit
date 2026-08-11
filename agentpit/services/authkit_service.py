"""Turning a WorkOS identity into an agentpit account.

WorkOS proves that somebody owns an email address. Everything that makes the
account an agentpit account -- the wallet, its private key, the API key, the
handle, the on-chain onboarding -- is made here, on the first successful
sign-in and never again.

There is no registration endpoint and no registration step. A person who has
never been here and a person who signs in daily take the same path; the only
difference is whether `WORKOS_USER_ID` already matches a row.
"""
import logging
from dataclasses import dataclass

from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import InvalidCredentialsError
from agentpit.domain.handles import pick_handle
from agentpit.auth.workos_client import WorkOsClient, WorkOsSession

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthKitSession:
    user: User
    access_token: str
    refresh_token: str


class AuthKitService:
    def __init__(self, *, db: DbSession, workos: WorkOsClient, onboard):
        self._db = db
        self._workos = workos
        # `AuthService._onboard_new_account` -- injected rather than imported so
        # the chain stays out of these tests, and so the two services do not
        # depend on each other's construction.
        self._onboard = onboard

    def send_code(self, email: str) -> None:
        self._workos.send_magic_auth_code(email)

    def sign_in(self, email: str, code: str) -> AuthKitSession:
        session = self._workos.authenticate_with_code(email, code)
        return AuthKitSession(
            user=self._resolve_account(session, create=True),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    def refresh(self, refresh_token: str) -> AuthKitSession:
        session = self._workos.refresh_session(refresh_token)
        return AuthKitSession(
            # `create=False`: a refresh proves a session is alive, not that a
            # person just proved ownership of an address. Minting an account
            # here would put a wallet behind a credential that never passed
            # through sign_in.
            user=self._resolve_account(session, create=False),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    def _resolve_account(self, session: WorkOsSession, *, create: bool) -> User:
        with self._db.read() as conn:
            user = TableRead.get_user_by_workos_id(conn, session.workos_user_id)
        if user is not None:
            return self._finish_onboarding(user)
        if not create:
            raise InvalidCredentialsError("invalid session")
        return self._create_account(session)

    def _finish_onboarding(self, user: User) -> User:
        """Onboard a row that has an account but never got a funded wallet.

        `_create_account` commits the row (and its WORKOS_USER_ID) before it
        calls `_onboard`, because onboarding is ~a second of chain round-trips
        and must not hold the write lock. So a chain that is down or restarting
        during somebody's first sign-in leaves a committed row with
        ONBOARDED_AT NULL, and every later sign-in would find it by WorkOS id
        and hand back a session for a wallet with no gas, no collateral and no
        approvals -- every order failing at trade time.

        `AuthService._maybe_reonboard` cannot repair that one: it returns early
        precisely when `onboarded_at is None`, because its own repair is for
        chain *wipes* and it needs the stamp to know the wallet was ever
        funded. This is the other half, and it is cheap: `onboarded_at` is
        already on the row we just read, so the healthy path costs nothing.
        """
        if user.onboarded_at is not None:
            return user
        log.info(
            "user %s has no ONBOARDED_AT — finishing onboarding on sign-in",
            user.user_id,
        )
        return self._onboard(user.user_id, user.eth_key)

    def _link_existing_account(self, session: WorkOsSession) -> User | None:
        """Adopt an account that predates this address's WORKOS_USER_ID.

        None when there is no such row. Otherwise the row, with the identity
        stamped on it -- an account the migration missed, or one made by
        `/register` before this shipped. Linking beats creating: a second row
        is a second wallet and a person whose positions have disappeared.
        Case-insensitive for the same reason `get_user_by_email_ci` exists:
        WorkOS reports a normalised address, ours was stored as typed.
        """
        with self._db.write() as conn:
            existing = TableRead.get_user_by_email_ci(conn, session.email)
            if existing is None:
                return None
            # The password on that row goes with the link -- see
            # `TableWrite.link_workos_identity` for why. Nobody ever verified
            # that whoever set it owns this address; the code we just mailed is
            # the only proof of ownership in play, so it takes the account
            # whole.
            if not TableWrite.link_workos_identity(
                conn, existing.user_id, session.workos_user_id
            ):
                # The row went away between the read above and this write.
                # Issuing a session for it would hand back credentials for an
                # account that no longer exists.
                log.warning("workos link found no row for user %s", existing.user_id)
                raise InvalidCredentialsError("invalid session")
        # `existing` was read before the stamp, so reflect it locally rather
        # than re-reading the row. Only the identity changed: the password is
        # deliberately left in place (see `TableWrite.link_workos_identity`),
        # and `has_password` must keep saying so -- the UI routes key export by
        # that flag, so a false here is the same dead end as clearing the hash,
        # reached through the payload instead of the database.
        return existing.model_copy(
            update={"workos_user_id": session.workos_user_id}
        )

    def _create_account(self, session: WorkOsSession) -> User:
        linked = self._link_existing_account(session)
        if linked is not None:
            # Outside its transaction, like the create path below: a linked row
            # can itself be one whose onboarding never finished.
            return self._finish_onboarding(linked)

        with self._db.write() as conn:
            handle = pick_handle(
                taken=lambda candidate: TableRead.handle_taken(conn, candidate)
            )
            user_id, acct, _api_key = TableWrite.create_user(
                conn, email=session.email, password_hash=None, handle=handle
            )
            TableWrite.set_workos_user_id(conn, user_id, session.workos_user_id)

        # Outside the transaction: onboarding is ~a second of chain round-trips
        # and must not hold a write lock, exactly as AuthService.register does it.
        return self._onboard(user_id, acct)
